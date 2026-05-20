# -*- coding: utf-8 -*-
import os
import tempfile
import shutil
import math
from pathlib import Path

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QSize, QRect, Qt
from qgis.PyQt.QtGui import QIcon, QImage, QPainter, QColor
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (
    QgsProject, 
    QgsMessageLog, 
    Qgis,
    QgsMapSettings,
    QgsMapRendererCustomPainterJob,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform
)

from .resources import *
from .pmtiles_exporter_dialog import PMTilesExporterDialog

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

        self.dlg.init_dialog()
        self.dlg.show()
        
        result = self.dlg.exec_()
        if result:
            self.export_pmtiles()

    # ==========================================
    # 出力処理 実装部
    # ==========================================
    def export_pmtiles(self):
        """
        出力形式 (XYZ / MBTiles / PMTiles) に応じて処理を分岐
        """
        output_path_str = self.dlg.txtOutputPath.text()
        if not output_path_str:
            self.iface.messageBar().pushMessage("エラー", "保存先が指定されていません。", level=Qgis.Critical)
            return

        fmt = self.dlg.get_output_format()
        extent = self._get_extent()
        min_zoom = self.dlg.spinMinZoom.value()
        max_zoom = self.dlg.spinMaxZoom.value()

        # 作業用の一時ディレクトリを作成
        tmp_dir = tempfile.mkdtemp()
        png_path = os.path.join(tmp_dir, "base_image.png")
        xyz_output_dir = os.path.join(tmp_dir, "tiles")

        self.iface.messageBar().pushMessage("PMTiles Exporter", "処理を開始しました...", level=Qgis.Info)

        try:
            # 1. 透過PNGとして出力 (アスペクト比維持)
            QgsMessageLog.logMessage("[1] ベースとなるPNG画像を生成中...", "PMTilesExporter", Qgis.Info)
            self.export_layers_to_png(png_path, extent=extent)
            
            # 2. XYZ タイル生成
            QgsMessageLog.logMessage(f"[2] XYZタイルの生成を開始: Z{min_zoom}-{max_zoom}", "PMTilesExporter", Qgis.Info)
            self.generate_xyz_tiles(png_path, xyz_output_dir, min_zoom, max_zoom, extent)
            
            # 3. 出力形式に応じた分岐処理
            if fmt == "xyz":
                QgsMessageLog.logMessage(f"[3] XYZタイルの仕上げ処理...", "PMTilesExporter", Qgis.Info)
                # index.html を自動生成
                self._generate_leaflet_html(xyz_output_dir, min_zoom, max_zoom)
                
                # Tempフォルダのタイル群を指定されたフォルダに移動/コピー
                if os.path.exists(output_path_str):
                    shutil.rmtree(output_path_str, ignore_errors=True)
                shutil.copytree(xyz_output_dir, output_path_str)
                
                self.iface.messageBar().pushMessage("完了", f"XYZタイルの出力が完了しました！", level=Qgis.Success)
                
            elif fmt == "mbtiles":
                QgsMessageLog.logMessage(f"[3] MBTiles 生成中...", "PMTilesExporter", Qgis.Info)
                mbtiles_path = os.path.join(tmp_dir, "temp.mbtiles")
                self._build_mbtiles_from_xyz(xyz_output_dir, mbtiles_path, min_zoom, max_zoom, extent)
                
                # 指定パスへコピー
                shutil.copy2(mbtiles_path, output_path_str)
                self.iface.messageBar().pushMessage("完了", f"MBTilesの出力が完了しました！", level=Qgis.Success)
                
            elif fmt == "pmtiles":
                QgsMessageLog.logMessage(f"[3] MBTiles 生成中...", "PMTilesExporter", Qgis.Info)
                mbtiles_path = os.path.join(tmp_dir, "temp.mbtiles")
                self._build_mbtiles_from_xyz(xyz_output_dir, mbtiles_path, min_zoom, max_zoom, extent)
                
                QgsMessageLog.logMessage(f"[4] PMTiles 変換中...", "PMTilesExporter", Qgis.Info)
                self._convert_mbtiles_to_pmtiles(mbtiles_path, output_path_str)
                
                self.iface.messageBar().pushMessage("完了", f"PMTilesの出力が完了しました！", level=Qgis.Success)

            # 成功したら設定を保存
            self.dlg.save_settings()
            
        except Exception as e:
            QgsMessageLog.logMessage(f"エラー: {str(e)}", "PMTilesExporter", Qgis.Critical)
            self.iface.messageBar().pushMessage("エラー", f"出力に失敗しました。ログを確認してください。\n{e}", level=Qgis.Critical)
        
        finally:
            # 終了後に Temp フォルダを削除
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def export_layers_to_png(self, output_path, extent=None, max_dim=4096):
        """現在のレイヤーを合成して1枚の PNG を出力する"""
        all_layers = [layer for layer in QgsProject.instance().layerTreeRoot().layerOrder()]
        selected_layers = self.dlg.get_selected_layers()
        layers = [layer for layer in all_layers if layer in selected_layers]

        if not layers:
            raise Exception("出力対象のレイヤーがありません。")

        settings = QgsMapSettings()
        settings.setLayers(layers)
        settings.setBackgroundColor(QColor(0, 0, 0, 0)) # 背景透過

        if extent is None:
            extent = self.iface.mapCanvas().extent()

        settings.setExtent(extent)

        ratio = extent.width() / extent.height()
        if ratio > 1.0:
            width = max_dim
            height = int(max_dim / ratio)
        else:
            height = max_dim
            width = int(max_dim * ratio)

        settings.setOutputSize(QSize(width, height))

        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(0) 

        painter = QPainter(image)
        job = QgsMapRendererCustomPainterJob(settings, painter)
        job.start()
        job.waitForFinished()
        painter.end()

        image.save(str(output_path), "PNG")
        return True

    def generate_xyz_tiles(self, png_path, output_dir, min_zoom, max_zoom, extent):
        """透過PNGを読み込み、指定されたズームレベルごとにXYZタイルを生成する"""
        source_image = QImage(png_path)
        if source_image.isNull():
            raise Exception("PNG画像の読み込みに失敗しました")

        crs_src = QgsProject.instance().crs()
        crs_3857 = QgsCoordinateReferenceSystem("EPSG:3857")
        transform = QgsCoordinateTransform(crs_src, crs_3857, QgsProject.instance())
        
        extent_3857 = transform.transformBoundingBox(extent)
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

        src_w = source_image.width()
        src_h = source_image.height()
        total_tiles_generated = 0

        for z in range(min_zoom, max_zoom + 1):
            t_min_x, t_max_y = meters_to_tile(min_x_m, max_y_m, z)
            t_max_x, t_min_y = meters_to_tile(max_x_m, min_y_m, z)

            z_dir = os.path.join(output_dir, str(z))
            os.makedirs(z_dir, exist_ok=True)

            for tx in range(t_min_x, t_max_x + 1):
                x_dir = os.path.join(z_dir, str(tx))
                os.makedirs(x_dir, exist_ok=True)

                for ty in range(t_max_y, t_min_y + 1):
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

        QgsMessageLog.logMessage(f"XYZタイル生成完了: 計 {total_tiles_generated} 枚のタイルを生成しました。", "PMTilesExporter", Qgis.Info)

    def _generate_leaflet_html(self, xyz_dir, min_zoom, max_zoom):
        """XYZ出力時に Leaflet 用の index.html を生成する"""
        html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>XYZ Tile Viewer</title>
<style>
html, body, #map {{ height: 100%; margin: 0; padding: 0; }}
</style>
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
</head>
<body>
<div id="map"></div>
<script>
var map = L.map('map').setView([0, 0], 15);

L.tileLayer('./{{z}}/{{x}}/{{y}}.png', {{
maxZoom: {max_zoom},
minZoom: {min_zoom},
tileSize: 256,
attribution: ''
}}).addTo(map);
</script>
</body>
</html>"""
        
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