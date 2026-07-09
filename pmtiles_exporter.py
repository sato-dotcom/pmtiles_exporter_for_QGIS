# -*- coding: utf-8 -*-
import os
import math
import time
import sqlite3
from pathlib import Path

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import (
    QSettings,
    QTranslator,
    QCoreApplication,
    QSize,
    QRect,
    Qt,
    pyqtSignal
)
from qgis.PyQt.QtGui import (
    QIcon,
    QImage,
    QPainter,
    QColor
)
from qgis.PyQt.QtWidgets import (
    QAction,
    QMessageBox
)

from qgis.core import (
    QgsProject,
    QgsRectangle,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMapSettings,
    QgsMapRendererParallelJob,
    QgsMessageLog,
    Qgis
)

from .pmtiles_exporter_dialog import PMTilesExporterDialog


def log(msg):
    """QGISのログパネルとコンソールにメッセージを出力する"""
    print(f"[PMTiles Exporter] {msg}")
    QgsMessageLog.logMessage(str(msg), "PMTiles Exporter", Qgis.Info)


class PMTilesExporter:
    """PMTiles Exporter for QGIS（全国版・XYZ/MBTiles/PMTiles対応）"""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr(u'&PMTiles Exporter')
        self.dlg = None

        # 翻訳（必要なら）
        locale = QSettings().value('locale/userLocale', 'ja_JP')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            f'pmtiles_exporter_{locale}.qm'
        )

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)
        else:
            self.translator = None

    # ---------------------------------------------------------
    # QGIS標準の tr ラッパ
    # ---------------------------------------------------------
    def tr(self, message):
        return QCoreApplication.translate('PMTilesExporter', message)

    # ---------------------------------------------------------
    # メニュー登録
    # ---------------------------------------------------------
    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None
    ):
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip:
            action.setStatusTip(status_tip)
        if whats_this:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.iface.addToolBarIcon(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    # ---------------------------------------------------------
    # GUI初期化
    # ---------------------------------------------------------
    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.add_action(
            icon_path,
            text=self.tr('PMTiles Exporter'),
            callback=self.run,
            parent=self.iface.mainWindow()
        )

    # ---------------------------------------------------------
    # アンロード
    # ---------------------------------------------------------
    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)

    # ---------------------------------------------------------
    # メイン起動
    # ---------------------------------------------------------
    def run(self):
        if self.dlg is None:
            self.dlg = PMTilesExporterDialog(self.iface.mainWindow())
            # ダイアログのOKボタンが押された時の処理を紐付け
            self.dlg.buttonBox.accepted.connect(self.start_export)

        self.dlg.load_settings()
        
        # モーダルとして実行せず、show() で開いたままにして進捗を見せる
        self.dlg.show()
        
    def start_export(self):
        """ダイアログのOKボタンが押された時の処理"""
        self.dlg.save_settings()
        
        # ボタンを無効化して連打を防ぐ
        self.dlg.buttonBox.setEnabled(False)
        
        try:
            success = self.export_tiles()
            if success:
                # 成功したらダイアログを閉じる
                self.dlg.accept()
        finally:
            # 処理が終わったらボタンを有効に戻す
            self.dlg.buttonBox.setEnabled(True)

    # ---------------------------------------------------------
    # タイル出力メイン
    # ---------------------------------------------------------
    def export_tiles(self):
        log("export_tiles: 処理を開始します。")
        output_folder = self.dlg.txtOutputPath.text().strip()
        if not output_folder:
            QMessageBox.warning(self.iface.mainWindow(), "PMTiles Exporter", "保存先フォルダを指定してください。")
            return False

        Path(output_folder).mkdir(parents=True, exist_ok=True)
        log(f"保存先フォルダ: {output_folder}")

        # 出力範囲とCRSの決定
        extent = None
        extent_crs = None

        if self.dlg.radLayer.isChecked():
            log("出力範囲モード: レイヤー結合範囲")
            extent = self.dlg.get_union_extent()
            if extent is None:
                QMessageBox.warning(self.iface.mainWindow(), "PMTiles Exporter", "表示されているレイヤーがありません。")
                return False
            extent_crs = self.dlg.get_extent_crs()
        else:
            log("出力範囲モード: 現在のキャンバス範囲")
            extent = self.iface.mapCanvas().extent()
            # キャンバスの場合も、データの本来のCRSを優先して取得する。
            layer_crs = self.dlg.get_extent_crs()
            if layer_crs and layer_crs.isValid():
                extent_crs = layer_crs
            else:
                extent_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

        log(f"元extent: {extent.toString()}")
        log(f"元CRS: {extent_crs.authid()}")

        # ズーム
        min_zoom = self.dlg.spinMinZoom.value()
        max_zoom = self.dlg.spinMaxZoom.value()
        log(f"ズームレベル: {min_zoom} から {max_zoom}")

        # タイル形式
        tile_format = self.dlg.cmbTileFormat.currentText()
        log(f"選択されたタイル形式: {tile_format}")

        # 進捗UI初期化
        self.dlg.init_progress()
        QCoreApplication.processEvents()

        try:
            if "XYZ" in tile_format:
                log("XYZタイルの生成を開始します...")
                self.export_xyz_tiles(output_folder, extent, extent_crs, min_zoom, max_zoom)
                QMessageBox.information(self.iface.mainWindow(), "PMTiles Exporter", "XYZタイルの出力が完了しました！")
                
            elif "MBTiles" in tile_format:
                log("MBTiles出力: まずXYZタイルを生成します...")
                self.export_xyz_tiles(output_folder, extent, extent_crs, min_zoom, max_zoom)
                
                mbtiles_path = os.path.join(output_folder, "output.mbtiles")
                log(f"MBTilesの生成を開始します: {mbtiles_path}")
                
                # Bounds計算用 (EPSG:4326)
                crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")
                transform_4326 = QgsCoordinateTransform(extent_crs, crs_4326, QgsProject.instance())
                extent_4326 = transform_4326.transformBoundingBox(extent)
                
                self.export_mbtiles_from_xyz(output_folder, mbtiles_path, min_zoom, max_zoom, extent_4326)
                QMessageBox.information(self.iface.mainWindow(), "PMTiles Exporter", "MBTilesの出力が完了しました！")

            elif "PMTiles" in tile_format:
                log("PMTiles出力: まずXYZタイルを生成します...")
                self.export_xyz_tiles(output_folder, extent, extent_crs, min_zoom, max_zoom)
                
                mbtiles_path = os.path.join(output_folder, "output.mbtiles")
                log(f"MBTilesの生成を開始します: {mbtiles_path}")
                
                # Bounds計算用 (EPSG:4326)
                crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")
                transform_4326 = QgsCoordinateTransform(extent_crs, crs_4326, QgsProject.instance())
                extent_4326 = transform_4326.transformBoundingBox(extent)
                
                self.export_mbtiles_from_xyz(output_folder, mbtiles_path, min_zoom, max_zoom, extent_4326)

                pmtiles_path = os.path.join(output_folder, "output.pmtiles")
                log(f"PMTilesの生成を開始します: {pmtiles_path}")
                
                self.export_pmtiles_from_mbtiles(mbtiles_path, pmtiles_path)
                QMessageBox.information(self.iface.mainWindow(), "PMTiles Exporter", "PMTilesの出力が完了しました！")

            self.dlg.finish_progress()
            log("エクスポート処理が正常に完了しました。")
            return True

        except Exception as e:
            log(f"エラー発生: {e}")
            import traceback
            log(traceback.format_exc())
            QMessageBox.critical(self.iface.mainWindow(), "PMTiles Exporter", f"タイル出力中にエラーが発生しました:\n{e}")
            return False

    # ---------------------------------------------------------
    # XYZタイル出力（CRS自動判定・透過PNG版）
    # ---------------------------------------------------------
    def export_xyz_tiles(self, output_folder, extent, extent_crs, min_zoom, max_zoom):
        """
        XYZタイルを {z}/{x}/{y}.png 形式で出力する
        """
        # 出力先 CRS（WebMercator）
        dest_crs = QgsCoordinateReferenceSystem("EPSG:3857")
        transform = QgsCoordinateTransform(extent_crs, dest_crs, QgsProject.instance())

        # 範囲をWebMercatorに変換
        try:
            extent_3857 = transform.transformBoundingBox(extent)
            log(f"WebMercator変換後のextent: {extent_3857.toString()}")
        except Exception as e:
            raise Exception(f"範囲の座標変換に失敗しました: {e}")

        WORLD_MIN = -20037508.342789244
        WORLD_MAX = 20037508.342789244
        WORLD_SIZE = WORLD_MAX - WORLD_MIN

        def x_to_mercator(x, z):
            tile_size = WORLD_SIZE / (2 ** z)
            return WORLD_MIN + x * tile_size

        def y_to_mercator(y, z):
            tile_size = WORLD_SIZE / (2 ** z)
            return WORLD_MAX - y * tile_size

        def mercator_to_tile_x(mx, z):
            tile_size = WORLD_SIZE / (2 ** z)
            return int((mx - WORLD_MIN) / tile_size)

        def mercator_to_tile_y(my, z):
            tile_size = WORLD_SIZE / (2 ** z)
            return int((WORLD_MAX - my) / tile_size)

        # ---------------------------------------------------------
        # レンダリング対象レイヤーの取得
        # ---------------------------------------------------------
        layers = self.dlg.get_selected_layers()
        if not layers:
            log("選択されたレイヤーがないため、キャンバス上の全レイヤーを対象とします。")
            layers = [l for l in QgsProject.instance().mapLayers().values()]
        
        log(f"レンダリング対象のレイヤー数: {len(layers)}")

        # ---------------------------------------------------------
        # 共通のMapSettingsを準備
        # ---------------------------------------------------------
        ms_base = QgsMapSettings()
        ms_base.setLayers(layers)
        # 背景を完全に透明に設定 (透過PNGのため)
        ms_base.setBackgroundColor(QColor(Qt.transparent))
        ms_base.setOutputSize(QSize(256, 256))
        ms_base.setDestinationCrs(dest_crs)
        ms_base.setFlag(QgsMapSettings.DrawLabeling, True)
        ms_base.setFlag(QgsMapSettings.Antialiasing, True)
        ms_base.setFlag(QgsMapSettings.UseAdvancedEffects, True)

        # ---------------------------------------------------------
        # タイル総数計算
        # ---------------------------------------------------------
        total_tiles = 0
        for z in range(min_zoom, max_zoom + 1):
            xmin = max(0, mercator_to_tile_x(extent_3857.xMinimum(), z))
            xmax = min(2**z - 1, mercator_to_tile_x(extent_3857.xMaximum(), z))
            ymin = max(0, mercator_to_tile_y(extent_3857.yMaximum(), z))
            ymax = min(2**z - 1, mercator_to_tile_y(extent_3857.yMinimum(), z))
            
            if xmin > xmax or ymin > ymax:
                continue
                
            total_tiles += (xmax - xmin + 1) * (ymax - ymin + 1)

        log(f"出力予定の総タイル数: {total_tiles}")

        if total_tiles == 0:
            raise Exception("出力対象のタイルが0件です。ズームレベルや出力範囲の設定を確認してください。")

        processed = 0
        self.dlg.label_progress.setText("XYZタイル作成中...")

        # ---------------------------------------------------------
        # タイル生成ループ
        # ---------------------------------------------------------
        for z in range(min_zoom, max_zoom + 1):
            xmin = max(0, mercator_to_tile_x(extent_3857.xMinimum(), z))
            xmax = min(2**z - 1, mercator_to_tile_x(extent_3857.xMaximum(), z))
            ymin = max(0, mercator_to_tile_y(extent_3857.yMaximum(), z))
            ymax = min(2**z - 1, mercator_to_tile_y(extent_3857.yMinimum(), z))

            for x in range(xmin, xmax + 1):
                for y in range(ymin, ymax + 1):

                    tile_x_min = x_to_mercator(x, z)
                    tile_x_max = x_to_mercator(x + 1, z)
                    tile_y_max = y_to_mercator(y, z)
                    tile_y_min = y_to_mercator(y + 1, z)

                    tile_extent = QgsRectangle(tile_x_min, tile_y_min, tile_x_max, tile_y_max)

                    # ベースの設定をコピーして範囲だけ更新
                    ms = QgsMapSettings(ms_base)
                    ms.setExtent(tile_extent)

                    job = QgsMapRendererParallelJob(ms)
                    job.start()
                    job.waitForFinished()

                    img = job.renderedImage()

                    # 保存先ディレクトリ作成
                    tile_dir = Path(output_folder) / str(z) / str(x)
                    tile_dir.mkdir(parents=True, exist_ok=True)

                    # PNG保存（透過）
                    file_path = tile_dir / f"{y}.png"
                    img.save(str(file_path), "PNG")

                    processed += 1
                    percent = (processed / total_tiles) * 100.0
                    self.dlg.update_progress(percent)
                    
                    # UIのフリーズを防ぐ
                    QCoreApplication.processEvents()

        log("XYZ画像のレンダリングと保存が完了しました。")

        # ---------------------------------------------------------
        # プレビュー用のHTML (Leaflet) を出力
        # ---------------------------------------------------------
        log("プレビュー用HTML (index.html) を生成します。")
        try:
            crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")
            transform_4326 = QgsCoordinateTransform(extent_crs, crs_4326, QgsProject.instance())
            extent_4326 = transform_4326.transformBoundingBox(extent)
            
            html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>XYZ Tile Preview</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    body {{ margin: 0; padding: 0; }}
    #map {{ width: 100vw; height: 100vh; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    var map = L.map('map');
    
    // 背景地図 (OpenStreetMap)
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      attribution: '&copy; OpenStreetMap contributors'
    }}).addTo(map);

    // 出力したXYZタイル
    L.tileLayer('./{{z}}/{{x}}/{{y}}.png', {{
      minZoom: {min_zoom},
      maxZoom: {max_zoom},
      tms: false
    }}).addTo(map);
    
    // 出力範囲に自動ズーム
    var bounds = [
      [{extent_4326.yMinimum()}, {extent_4326.xMinimum()}],
      [{extent_4326.yMaximum()}, {extent_4326.xMaximum()}]
    ];
    map.fitBounds(bounds);
  </script>
</body>
</html>"""
            
            html_path = Path(output_folder) / "index.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            log("HTMLの生成が完了しました。")
        except Exception as e:
            log(f"HTMLの生成中にエラーが発生しましたが、タイルの出力は完了しています: {e}")


    # ---------------------------------------------------------
    # XYZ から MBTiles への変換処理
    # ---------------------------------------------------------
    def export_mbtiles_from_xyz(self, xyz_folder, mbtiles_path, min_zoom, max_zoom, extent_4326):
        """
        生成済みのXYZタイルをMBTiles (SQLite) にパックする
        Y座標はTMS規格に沿って反転して格納する
        """
        if os.path.exists(mbtiles_path):
            os.remove(mbtiles_path)
            
        conn = sqlite3.connect(mbtiles_path)
        cursor = conn.cursor()
        
        # テーブルとインデックスの作成
        cursor.execute("CREATE TABLE metadata (name text, value text);")
        cursor.execute("CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob);")
        cursor.execute("CREATE UNIQUE INDEX tile_index on tiles (zoom_level, tile_column, tile_row);")
        
        # メタデータの計算
        bounds_str = f"{extent_4326.xMinimum()},{extent_4326.yMinimum()},{extent_4326.xMaximum()},{extent_4326.yMaximum()}"
        center_x = (extent_4326.xMinimum() + extent_4326.xMaximum()) / 2.0
        center_y = (extent_4326.yMinimum() + extent_4326.yMaximum()) / 2.0
        center_str = f"{center_x},{center_y},{min_zoom}"
        
        metadata = [
            ("name", "QGIS PMTiles Exporter"),
            ("type", "overlay"),
            ("version", "1.1"),
            ("description", "Exported from QGIS"),
            ("format", "png"),
            ("bounds", bounds_str),
            ("center", center_str),
            ("minzoom", str(min_zoom)),
            ("maxzoom", str(max_zoom))
        ]
        
        cursor.executemany("INSERT INTO metadata (name, value) VALUES (?, ?);", metadata)
        
        log("XYZタイルを読み込み、MBTilesデータベースに格納しています...")
        
        # タイルの総数を取得する
        tile_count = 0
        for z in range(min_zoom, max_zoom + 1):
            z_dir = Path(xyz_folder) / str(z)
            if not z_dir.exists():
                continue
            for x_dir in z_dir.iterdir():
                if not x_dir.is_dir():
                    continue
                tile_count += len(list(x_dir.glob("*.png")))
                
        if tile_count == 0:
            log("格納するタイルが見つかりませんでした。")
            conn.close()
            return
            
        # UIリセット
        processed = 0
        self.dlg.label_progress.setText("MBTiles作成中...")
        self.dlg.progressBar.setValue(0)
        QCoreApplication.processEvents()

        # BLOB格納ループ
        for z in range(min_zoom, max_zoom + 1):
            z_dir = Path(xyz_folder) / str(z)
            if not z_dir.exists():
                continue
            
            for x_dir in z_dir.iterdir():
                if not x_dir.is_dir():
                    continue
                
                try:
                    x = int(x_dir.name)
                except ValueError:
                    continue
                    
                for y_file in x_dir.glob("*.png"):
                    try:
                        y = int(y_file.stem)
                    except ValueError:
                        continue
                        
                    # MBTiles仕様 (TMS) に合わせてY座標を反転する
                    # tms_y = (2^z) - 1 - y
                    tms_y = (1 << z) - 1 - y
                    
                    with open(y_file, "rb") as f:
                        tile_data = f.read()
                        
                    cursor.execute(
                        "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?);",
                        (z, x, tms_y, sqlite3.Binary(tile_data))
                    )
                    
                    processed += 1
                    
                    # 100ファイルごとにUIを更新する
                    if processed % 100 == 0:
                        percent = (processed / tile_count) * 100.0
                        self.dlg.update_progress(percent)
                        QCoreApplication.processEvents()

        conn.commit()
        conn.close()
        
        self.dlg.update_progress(100.0)
        log(f"MBTilesの生成が完了しました！ 総格納タイル数: {processed}")

    # ---------------------------------------------------------
    # MBTiles から PMTiles への変換処理
    # ---------------------------------------------------------
    def export_pmtiles_from_mbtiles(self, mbtiles_path, pmtiles_path):
        """
        生成済みのMBTilesを読み込み、PMTiles v3形式に変換して出力する
        """
        self.dlg.label_progress.setText("PMTiles作成中...")
        self.dlg.progressBar.setValue(0)
        QCoreApplication.processEvents()
        
        try:
            import pmtiles
        except ImportError:
            raise Exception("pmtilesパッケージがインストールされていません。QGISのPython環境で 'pip install pmtiles' を実行してください。")
            
        if os.path.exists(pmtiles_path):
            os.remove(pmtiles_path)
            
        log("pmtilesモジュールを使用してPMTilesへ変換しています...")
        
        # ユーザー指定の convert_mbtiles を優先し、別名の実装(mbtiles_to_pmtiles)も考慮
        try:
            if hasattr(pmtiles, 'convert_mbtiles'):
                pmtiles.convert_mbtiles(mbtiles_path, pmtiles_path)
            else:
                try:
                    from pmtiles.convert import mbtiles_to_pmtiles
                    mbtiles_to_pmtiles(mbtiles_path, pmtiles_path)
                except ImportError:
                    # 最終手段としてそのまま呼んでエラー内容を自然に表示させる
                    pmtiles.convert_mbtiles(mbtiles_path, pmtiles_path)
        except Exception as e:
            raise Exception(f"PMTilesへの変換処理に失敗しました: {e}")
                
        self.dlg.update_progress(100.0)
        log(f"PMTilesの生成が完了しました！ 出力先: {pmtiles_path}")