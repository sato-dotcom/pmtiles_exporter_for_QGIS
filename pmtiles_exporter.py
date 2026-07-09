# -*- coding: utf-8 -*-
import os
import math
import time
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
    QgsMapRendererParallelJob
)

from .pmtiles_exporter_dialog import PMTilesExporterDialog


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

        self.dlg.load_settings()

        result = self.dlg.exec_()
        if result == QtWidgets.QDialog.Accepted:
            self.dlg.save_settings()
            self.export_tiles()

    # ---------------------------------------------------------
    # タイル出力メイン
    # ---------------------------------------------------------
    def export_tiles(self):
        output_folder = self.dlg.txtOutputPath.text().strip()
        if not output_folder:
            QMessageBox.warning(self.iface.mainWindow(), "PMTiles Exporter",
                                "保存先フォルダを指定してください。")
            return

        Path(output_folder).mkdir(parents=True, exist_ok=True)

        # 出力範囲
        if self.dlg.radLayer.isChecked():
            extent = self.dlg.get_union_extent()
            if extent is None:
                QMessageBox.warning(self.iface.mainWindow(), "PMTiles Exporter",
                                    "レイヤー結合範囲が取得できませんでした。")
                return
            extent_crs = self.dlg.get_extent_crs()
        else:
            extent = self.iface.mapCanvas().extent()
            extent_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

        # ズーム
        min_zoom = self.dlg.spinMinZoom.value()
        max_zoom = self.dlg.spinMaxZoom.value()

        # タイル形式
        tile_format = self.dlg.cmbTileFormat.currentText()

        # 進捗
        self.dlg.init_progress()

        try:
            if "XYZ" in tile_format:
                self.export_xyz_tiles(output_folder, extent, extent_crs, min_zoom, max_zoom)

            elif "MBTiles" in tile_format:
                QMessageBox.information(self.iface.mainWindow(), "PMTiles Exporter",
                                        "MBTiles出力はまだ未実装です。")

            elif "PMTiles" in tile_format:
                QMessageBox.information(self.iface.mainWindow(), "PMTiles Exporter",
                                        "PMTiles出力はまだ未実装です.")

            self.dlg.finish_progress()

        except Exception as e:
            QMessageBox.critical(self.iface.mainWindow(), "PMTiles Exporter",
                                 f"タイル出力中にエラーが発生しました:\n{e}")

    # ---------------------------------------------------------
    # XYZタイル出力（CRS自動判定版）
    # ---------------------------------------------------------
    def export_xyz_tiles(self, output_folder, extent, extent_crs, min_zoom, max_zoom):
        """
        XYZタイルを {z}/{x}/{y}.png 形式で出力する
        """

        # 出力先 CRS（WebMercator）
        dest_crs = QgsCoordinateReferenceSystem("EPSG:3857")
        transform = QgsCoordinateTransform(extent_crs, dest_crs, QgsProject.instance())

        # 範囲をWebMercatorに変換
        extent_3857 = transform.transformBoundingBox(extent)

        WORLD_MIN = -20037508.34
        WORLD_MAX = 20037508.34
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

        # タイル総数計算
        total_tiles = 0
        for z in range(min_zoom, max_zoom + 1):
            xmin = mercator_to_tile_x(extent_3857.xMinimum(), z)
            xmax = mercator_to_tile_x(extent_3857.xMaximum(), z)
            ymin = mercator_to_tile_y(extent_3857.yMaximum(), z)
            ymax = mercator_to_tile_y(extent_3857.yMinimum(), z)
            total_tiles += (xmax - xmin + 1) * (ymax - ymin + 1)

        processed = 0

        # タイル生成ループ
        for z in range(min_zoom, max_zoom + 1):
            xmin = mercator_to_tile_x(extent_3857.xMinimum(), z)
            xmax = mercator_to_tile_x(extent_3857.xMaximum(), z)
            ymin = mercator_to_tile_y(extent_3857.yMaximum(), z)
            ymax = mercator_to_tile_y(extent_3857.yMinimum(), z)

            for x in range(xmin, xmax + 1):
                for y in range(ymin, ymax + 1):

                    tile_x_min = x_to_mercator(x, z)
                    tile_x_max = x_to_mercator(x + 1, z)
                    tile_y_max = y_to_mercator(y, z)
                    tile_y_min = y_to_mercator(y + 1, z)

                    tile_extent = QgsRectangle(tile_x_min, tile_y_min, tile_x_max, tile_y_max)

                    ms = QgsMapSettings()
                    ms.setLayers([l for l in QgsProject.instance().mapLayers().values()])
                    ms.setBackgroundColor(QColor(255, 255, 255, 0))
                    ms.setExtent(tile_extent)
                    ms.setOutputSize(QSize(256, 256))
                    ms.setDestinationCrs(dest_crs)

                    job = QgsMapRendererParallelJob(ms)
                    job.start()
                    job.waitForFinished()

                    img = job.renderedImage()

                    tile_path = Path(output_folder) / str(z) / str(x)
                    tile_path.mkdir(parents=True, exist_ok=True)

                    img.save(str(tile_path / f"{y}.png"), "PNG")

                    processed += 1
                    percent = (processed / total_tiles) * 100.0
                    self.dlg.update_progress(percent)
                    
                    # ★ここを追記しました：UIのフリーズを防ぎます
                    QCoreApplication.processEvents()

        # ---------------------------------------------------------
        # タイル出力完了後、プレビュー用のHTML (Leaflet) を出力
        # ---------------------------------------------------------
        try:
            # Leafletで読み込みやすいように、中心座標(緯度経度: EPSG4326)を計算する
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
        except Exception as e:
            # HTML生成のエラーはメインの処理を止めないよう無視する
            pass