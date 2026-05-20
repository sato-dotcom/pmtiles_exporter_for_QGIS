# -*- coding: utf-8 -*-
import os
import tempfile
import shutil
import math
import time
from pathlib import Path

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QSize, QRect, Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon, QImage, QPainter, QColor
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (
    QgsProject, 
    QgsMessageLog, 
    Qgis,
    QgsMapSettings,
    QgsMapRendererCustomPainterJob,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsTask,
    QgsApplication,
    QgsRectangle
)

from .resources import *
from .pmtiles_exporter_dialog import PMTilesExporterDialog


class ExportPmtilesTask(QgsTask):
    """QgsTaskを使用してバックグラウンドで出力処理を行うクラス"""

    def __init__(self, map_settings, output_path, fmt, extent_3857_tuple, min_zoom, max_zoom,
                 generate_xyz_func, generate_mbtiles_func, convert_pmtiles_func, generate_leaflet_func, finish_func):
        QgsMessageLog.logMessage("TASK INIT CALLED", "PMTilesExporter", Qgis.Info)
        super().__init__("PMTiles Export Task", QgsTask.CanCancel)
        self.map_settings = QgsMapSettings(map_settings)
        self.output_path = output_path
        self.fmt = fmt
        self.extent_3857_tuple = extent_3857_tuple
        self.min_zoom = min_zoom
        self.max_zoom = max_zoom
        
        # UIやQgsProjectに依存しない純粋な関数を保持
        self.generate_xyz = generate_xyz_func
        self.generate_mbtiles = generate_mbtiles_func
        self.convert_pmtiles = convert_pmtiles_func
        self.generate_leaflet = generate_leaflet_func
        self.finish_func = finish_func
        
        self.exception = None
        self.tmp_dir = None
        self.start_time = 0
        QgsMessageLog.logMessage("TASK INIT END", "PMTilesExporter", Qgis.Info)

    def run(self):
        try:
            xmin, ymin, xmax, ymax = self.extent_3857_tuple
            self.extent_3857 = QgsRectangle(xmin, ymin, xmax, ymax)

            QgsMessageLog.logMessage("TASK RUN STARTED", "PMTilesExporter", Qgis.Info)
            QgsMessageLog.logMessage("TASK RUN ENTERED", "PMTilesExporter", Qgis.Info)
            self.start_time = time.time()
            self.tmp_dir = tempfile.mkdtemp()
            png_path = os.path.join(self.tmp_dir, "base_image.png")
            xyz_output_dir = os.path.join(self.tmp_dir, "tiles")

            # 1. 透過PNG生成 (0% ～ 10%)
            self.setProgress(0)
            QgsMessageLog.logMessage("[1] ベースとなるPNG画像を生成中...", "PMTilesExporter", Qgis.Info)
            
            width = self.map_settings.outputSize().width()
            height = self.map_settings.outputSize().height()
            image = QImage(width, height, QImage.Format_ARGB32)
            image.fill(0) 

            painter = QPainter(image)
            job = QgsMapRendererCustomPainterJob(self.map_settings, painter)
            job.start()
            job.waitForFinished()
            painter.end()

            image.save(str(png_path), "PNG")
            
            if self.isCanceled(): 
                return False

            # 2. XYZ タイル生成 (10% ～ 90%)
            self.setProgress(10)
            QgsMessageLog.logMessage(f"[2] XYZタイルの生成を開始: Z{self.min_zoom}-{self.max_zoom}", "PMTilesExporter", Qgis.Info)
            
            def progress_cb(current, total):
                if self.isCanceled(): 
                    return False
                
                percent = 10 + int((current / total) * 80)
                self.setProgress(percent)
                return True

            self.generate_xyz(png_path, xyz_output_dir, self.min_zoom, self.max_zoom, self.extent_3857, progress_cb)
            
            if self.isCanceled(): 
                return False

            # 3. 出力形式に応じた分岐処理 (90% ～ 100%)
            self.setProgress(90)
            
            if self.fmt == "xyz":
                QgsMessageLog.logMessage(f"[3] XYZタイルの仕上げ処理...", "PMTilesExporter", Qgis.Info)
                self.generate_leaflet(xyz_output_dir, self.min_zoom, self.max_zoom)
                if os.path.exists(self.output_path):
                    shutil.rmtree(self.output_path, ignore_errors=True)
                shutil.copytree(xyz_output_dir, self.output_path)
                
            elif self.fmt == "mbtiles":
                QgsMessageLog.logMessage(f"[3] MBTiles 生成中...", "PMTilesExporter", Qgis.Info)
                mbtiles_path = os.path.join(self.tmp_dir, "temp.mbtiles")
                self.generate_mbtiles(xyz_output_dir, mbtiles_path, self.min_zoom, self.max_zoom, self.extent_3857)
                shutil.copy2(mbtiles_path, self.output_path)
                
            elif self.fmt == "pmtiles":
                QgsMessageLog.logMessage(f"[3] MBTiles 生成中...", "PMTilesExporter", Qgis.Info)
                mbtiles_path = os.path.join(self.tmp_dir, "temp.mbtiles")
                self.generate_mbtiles(xyz_output_dir, mbtiles_path, self.min_zoom, self.max_zoom, self.extent_3857)
                
                self.setProgress(95)
                QgsMessageLog.logMessage(f"[4] PMTiles 変換中...", "PMTilesExporter", Qgis.Info)
                self.convert_pmtiles(mbtiles_path, self.output_path)

            QgsMessageLog.logMessage("TASK RUN COMPLETED", "PMTilesExporter", Qgis.Info)
            return True

        except Exception as e:
            self.exception = e
            import traceback
            QgsMessageLog.logMessage(f"TASK RUN EXCEPTION: {str(e)}", "PMTilesExporter", Qgis.Critical)
            QgsMessageLog.logMessage(f"エラー詳細: {traceback.format_exc()}", "PMTilesExporter", Qgis.Critical)
            return False

    def finished(self, result):
        QgsMessageLog.logMessage("TASK FINISHED CALLED", "PMTilesExporter", Qgis.Info)
        QgsMessageLog.logMessage(f"TASK FINISHED result={result}", "PMTilesExporter", Qgis.Info)
        if self.tmp_dir:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
            
        # UIの更新処理は渡されたコールバック関数でメインスレッドに委譲
        if self.finish_func:
            self.finish_func(result, self.fmt, self.exception, self.isCanceled())


class PMTilesExporter:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor."""
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr(u'&PMTiles Exporter for QGIS')
        self.first_start = None

    def tr(self, message):
        return QCoreApplication.translate('PMTilesExporter', message)

    def add_action(self, icon_path, text, callback, enabled_flag=True, add_to_menu=True, add_to_toolbar=True, status_tip=None, whats_this=None, parent=None):
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)
        if whats_this is not None:
            action.setWhatsThis(whats_this)
        if add_to_toolbar:
            self.iface.addToolBarIcon(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    def initGui(self):
        icon_path = ':/plugins/pmtiles_exporter/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'PMTiles Exporter'),
            callback=self.run,
            parent=self.iface.mainWindow())
        self.first_start = True

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.tr(u'&PMTiles Exporter for QGIS'), action)
            self.iface.removeToolBarIcon(action)

    def run(self):
        if self.first_start == True:
            self.first_start = False
            self.dlg = PMTilesExporterDialog()
            # 「出力する」ボタン（OKボタン）がクリックされた時の独自処理を接続
            self.dlg.buttonBox.accepted.connect(self.start_export_task)

        self.dlg.init_dialog()
        # 非同期タスクを使用するため、モードレスで開くことでUIのブロックを防ぐ
        self.dlg.show()
        
    def start_export_task(self):
        """UIから設定を取得し、非同期タスクを開始する"""
        output_path_str = self.dlg.txtOutputPath.text()
        if not output_path_str:
            self.iface.messageBar().pushMessage("エラー", "保存先が指定されていません。", level=Qgis.Critical)
            return

        fmt = self.dlg.get_output_format()
        extent = self._get_extent()
        min_zoom = self.dlg.spinMinZoom.value()
        max_zoom = self.dlg.spinMaxZoom.value()

        # 出力対象のレイヤーを取得
        all_layers = [layer for layer in QgsProject.instance().layerTreeRoot().layerOrder()]
        selected_layers = self.dlg.get_selected_layers()
        layers = [layer for layer in all_layers if layer in selected_layers]

        if not layers:
            self.iface.messageBar().pushMessage("エラー", "出力対象のレイヤーがありません。", level=Qgis.Critical)
            return

        # ボタンを無効化しプログレスを初期状態に
        self.dlg.set_export_button_enabled(False)
        self.dlg.init_progress()
        self.iface.messageBar().pushMessage("PMTiles Exporter", "バックグラウンド処理を開始しました...", level=Qgis.Info)

        # レンダリング用の設定をメインスレッドで作成
        settings = QgsMapSettings()
        settings.setLayers(layers)
        settings.setBackgroundColor(QColor(0, 0, 0, 0)) # 背景透過
        settings.setExtent(extent)

        ratio = extent.width() / extent.height()
        max_dim = 4096
        if ratio > 1.0:
            width = max_dim
            height = int(max_dim / ratio)
        else:
            height = max_dim
            width = int(max_dim * ratio)
        settings.setOutputSize(QSize(width, height))

        QgsMessageLog.logMessage(f"Extent: {extent.toString()}", "PMTilesExporter", Qgis.Info)
        QgsMessageLog.logMessage(f"Output size: {width} x {height}", "PMTilesExporter", Qgis.Info)

        # 座標系変換もメインスレッドのQgsProjectに依存するため事前に計算しておく
        crs_src = QgsProject.instance().crs()
        crs_3857 = QgsCoordinateReferenceSystem("EPSG:3857")
        transform = QgsCoordinateTransform(crs_src, crs_3857, QgsProject.instance())
        extent_3857 = transform.transformBoundingBox(extent)

        extent_3857_tuple = (
            extent_3857.xMinimum(),
            extent_3857.yMinimum(),
            extent_3857.xMaximum(),
            extent_3857.yMaximum()
        )

        # QgsTask を使って非同期実行
        # exporter オブジェクト全体ではなく、個別の関数（callable）を渡す
        task = ExportPmtilesTask(
            map_settings=settings,
            output_path=output_path_str,
            fmt=fmt,
            extent_3857_tuple=extent_3857_tuple,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            generate_xyz_func=self._generate_xyz_tiles_bg,
            generate_mbtiles_func=self._build_mbtiles_from_xyz,
            convert_pmtiles_func=self._convert_mbtiles_to_pmtiles,
            generate_leaflet_func=self._generate_leaflet_html,
            finish_func=self._on_task_finished
        )
        # スレッド間通信のためQueuedConnectionを使用
        task.progressChanged.connect(self.dlg.update_progress, Qt.QueuedConnection)
        QgsApplication.taskManager().addTask(task)

    def _on_task_finished(self, result, fmt, exception, is_canceled):
        """タスク完了時にメインスレッドでUI更新を行う"""
        if result:
            self.dlg.finish_progress()
            self.dlg.save_settings()
            self.iface.messageBar().pushMessage("完了", f"{fmt.upper()}の出力が完了しました！", level=Qgis.Success)
        else:
            if is_canceled:
                self.iface.messageBar().pushMessage("キャンセル", "処理がキャンセルされました。", level=Qgis.Info)
                self.dlg.label_progress.setText("キャンセルされました。")
            else:
                self.iface.messageBar().pushMessage("エラー", f"出力に失敗しました: {exception}", level=Qgis.Critical)
                self.dlg.label_progress.setText("エラーが発生しました。")
            
        # ボタンを再度有効化する
        self.dlg.set_export_button_enabled(True)

    # ==========================================
    # バックグラウンド用処理メソッド
    # ==========================================
    def _generate_xyz_tiles_bg(self, png_path, output_dir, min_zoom, max_zoom, extent_3857, progress_cb=None):
        """透過PNGを読み込み、指定されたズームレベルごとにXYZタイルを生成する"""
        source_image = QImage(png_path)
        if source_image.isNull():
            raise Exception("PNG画像の読み込みに失敗しました")

        min_x_m = extent_3857.xMinimum()
        max_x_m = extent_3857.xMaximum()
        min_y_m = extent_3857.yMinimum()
        max_y_m = extent_3857.yMaximum()

        MAX_EXTENT = 20037508.342789244

        def meters_to_tile(x, y, z):
            res = (2 * MAX_EXTENT) / (256 * (2 ** z))
            px = (x + MAX_EXTENT) / res
            py = (MAX_EXTENT - y) / res
            return int(px / 256), int(py / 256)

        def tile_bounds_meters(tx, ty, z):
            res = (2 * MAX_EXTENT) / (256 * (2 ** z))
            min_x = tx * 256 * res - MAX_EXTENT
            max_y = MAX_EXTENT - ty * 256 * res
            max_x = min_x + 256 * res
            min_y = max_y - 256 * res
            return min_x, min_y, max_x, max_y

        # 総タイル数の事前計算（進捗管理用）
        total_tiles_to_generate = 0
        for z in range(min_zoom, max_zoom + 1):
            t_min_x, t_max_y = meters_to_tile(min_x_m, max_y_m, z)
            t_max_x, t_min_y = meters_to_tile(max_x_m, min_y_m, z)
            total_tiles_to_generate += (t_max_x - t_min_x + 1) * (t_min_y - t_max_y + 1)

        if total_tiles_to_generate == 0:
            return

        src_w = source_image.width()
        src_h = source_image.height()
        
        total_tiles_generated = 0
        processed_tiles = 0

        for z in range(min_zoom, max_zoom + 1):
            t_min_x, t_max_y = meters_to_tile(min_x_m, max_y_m, z)
            t_max_x, t_min_y = meters_to_tile(max_x_m, min_y_m, z)

            z_dir = os.path.join(output_dir, str(z))
            os.makedirs(z_dir, exist_ok=True)

            for tx in range(t_min_x, t_max_x + 1):
                x_dir = os.path.join(z_dir, str(tx))
                os.makedirs(x_dir, exist_ok=True)

                for ty in range(t_max_y, t_min_y + 1):
                    processed_tiles += 1
                    # 1% 進むごとにコールバックで進捗を更新
                    if processed_tiles % max(1, total_tiles_to_generate // 100) == 0:
                        if progress_cb and not progress_cb(processed_tiles, total_tiles_to_generate):
                            return # キャンセル

                    t_b_min_x, t_b_min_y, t_b_max_x, t_b_max_y = tile_bounds_meters(tx, ty, z)

                    x_ratio_start = (t_b_min_x - min_x_m) / (max_x_m - min_x_m)
                    x_ratio_end = (t_b_max_x - min_x_m) / (max_x_m - min_x_m)
                    
                    y_ratio_start = (max_y_m - t_b_max_y) / (max_y_m - min_y_m)
                    y_ratio_end = (max_y_m - t_b_min_y) / (max_y_m - min_y_m)

                    px_start = int(x_ratio_start * src_w)
                    px_end = int(x_ratio_end * src_w)
                    py_start = int(y_ratio_start * src_h)
                    py_end = int(y_ratio_end * src_h)

                    if px_end <= 0 or px_start >= src_w or py_end <= 0 or py_start >= src_h:
                        continue

                    c_x = max(0, px_start)
                    c_y = max(0, py_start)
                    c_w = min(src_w, px_end) - c_x
                    c_h = min(src_h, py_end) - c_y

                    if c_w <= 0 or c_h <= 0:
                        continue

                    clip_rect = QRect(c_x, c_y, c_w, c_h)
                    clipped_image = source_image.copy(clip_rect)

                    tile_image = QImage(256, 256, QImage.Format_ARGB32)
                    tile_image.fill(QColor(0, 0, 0, 0))

                    tile_px_w = px_end - px_start
                    tile_px_h = py_end - py_start

                    if tile_px_w <= 0 or tile_px_h <= 0:
                        continue

                    offset_x = c_x - px_start
                    offset_y = c_y - py_start

                    draw_x = int((offset_x / tile_px_w) * 256)
                    draw_y = int((offset_y / tile_px_h) * 256)
                    draw_w = int((c_w / tile_px_w) * 256)
                    draw_h = int((c_h / tile_px_h) * 256)

                    if draw_w > 0 and draw_h > 0:
                        scaled_clip = clipped_image.scaled(draw_w, draw_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                        painter = QPainter(tile_image)
                        painter.drawImage(draw_x, draw_y, scaled_clip)
                        painter.end()

                        tile_path = os.path.join(x_dir, f"{ty}.png")
                        tile_image.save(tile_path, "PNG")
                        total_tiles_generated += 1
                        
        if progress_cb:
            progress_cb(total_tiles_to_generate, total_tiles_to_generate)
            
        QgsMessageLog.logMessage(f"XYZタイル生成完了: 計 {total_tiles_generated} 枚のタイルを生成しました。", "PMTilesExporter", Qgis.Info)

    def _generate_leaflet_html(self, xyz_dir, min_zoom, max_zoom):
        """XYZ出力時に Leaflet 用の index.html を生成する"""
        html_content = f"""[HTML_START]
[HEAD_START]
<meta charset="utf-8" />
<title>XYZ Tile Viewer</title>
[STYLE_START]
html, body, #map {{ height: 100%; margin: 0; padding: 0; }}
[STYLE_END]
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
[SCRIPT_START] src="https://unpkg.com/leaflet/dist/leaflet.js">[SCRIPT_END]
[HEAD_END]
[BODY_START]
<div id="map"></div>
[SCRIPT_START]
var map = L.map('map').setView([0, 0], 15);

L.tileLayer('./{{z}}/{{x}}/{{y}}.png', {{
maxZoom: {max_zoom},
minZoom: {min_zoom},
tileSize: 256,
attribution: ''
}}).addTo(map);
[SCRIPT_END]
[BODY_END]
[HTML_END]"""
        
        index_path = os.path.join(xyz_dir, "index.html")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(html_content)

    def _get_extent(self):
        """出力範囲の取得"""
        if self.dlg.radCanvas.isChecked():
            return self.iface.mapCanvas().extent()
        elif self.dlg.radLayer.isChecked():
            layers = self.dlg.get_selected_layers()
            if not layers:
                return self.iface.mapCanvas().extent()
            extent = layers[0].extent()
            for layer in layers[1:]:
                extent.combineExtentWith(layer.extent())
            return extent
        else:
            return self.iface.mapCanvas().extent()

    # ==========================================
    # 次回以降実装予定のモック関数群
    # ==========================================
    def _build_mbtiles_from_xyz(self, xyz_dir, mbtiles_path, min_zoom, max_zoom, extent):
        """出力したXYZタイル群から SQLite(MBTiles) を生成（モック）"""
        QgsMessageLog.logMessage(f"[MBTiles] モック構築完了", "PMTilesExporter", Qgis.Info)

    def _convert_mbtiles_to_pmtiles(self, mbtiles_path, output_path):
        """MBTiles を PMTiles に変換（モック）"""
        QgsMessageLog.logMessage(f"[PMTiles] モック変換完了", "PMTilesExporter", Qgis.Info)