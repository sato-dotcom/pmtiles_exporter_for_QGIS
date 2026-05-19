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
        [1] PNG出力 -> [2] XYZ生成 -> [3] MBTiles -> [4] PMTiles の一連のフロー
        """
        output_path_str = self.dlg.txtOutputPath.text()
        if not output_path_str:
            self.iface.messageBar().pushMessage("エラー", "保存先が指定されていません。", level=Qgis.Critical)
            return

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
            QgsMessageLog.logMessage("[1/4] ベースとなるPNG画像を生成中...", "PMTilesExporter", Qgis.Info)
            self.export_layers_to_png(png_path, extent=extent)
            
            # 2. XYZ タイル生成
            QgsMessageLog.logMessage(f"[2/4] XYZタイルの生成を開始: Z{min_zoom}-{max_zoom}", "PMTilesExporter", Qgis.Info)
            self.generate_xyz_tiles(png_path, xyz_output_dir, min_zoom, max_zoom, extent)
            
            # 3. MBTiles 生成 (現在はモック)
            mbtiles_path = os.path.join(tmp_dir, "temp.mbtiles")
            self._build_mbtiles_from_xyz(xyz_output_dir, mbtiles_path, min_zoom, max_zoom, extent)
            
            # 4. PMTiles 変換 (現在はモック)
            self._convert_mbtiles_to_pmtiles(mbtiles_path, output_path_str)

            # 成功したら設定を保存
            self.dlg.save_settings()
            self.iface.messageBar().pushMessage("PMTiles Exporter", f"処理完了（現在はXYZ生成まで動作）", level=Qgis.Success)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"エラー: {str(e)}", "PMTilesExporter", Qgis.Critical)
            self.iface.messageBar().pushMessage("エラー", f"出力に失敗しました。ログを確認してください。\n{e}", level=Qgis.Critical)
        
        # 本番では tmp_dir を削除する処理 (shutil.rmtree) を入れると良いです
        # shutil.rmtree(tmp_dir, ignore_errors=True)

    def export_layers_to_png(self, output_path, extent=None, max_dim=4096):
        """
        現在のレイヤーを合成して1枚の PNG を出力する。
        ※地図が歪まないよう、extent のアスペクト比を維持して出力します。
        """
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

        # アスペクト比を維持してサイズを決定 (最大サイズを max_dim に合わせる)
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
        """
        透過PNGを読み込み、指定されたズームレベルごとにXYZタイルを生成する。
        Slippy Map (Webメルカトル) の座標計算を行い、正しい位置で分割します。
        """
        source_image = QImage(png_path)
        if source_image.isNull():
            raise Exception("PNG画像の読み込みに失敗しました")

        # 座標系を EPSG:3857 (Web Mercator) に変換して正確なタイル位置を計算する
        crs_src = QgsProject.instance().crs()
        crs_3857 = QgsCoordinateReferenceSystem("EPSG:3857")
        transform = QgsCoordinateTransform(crs_src, crs_3857, QgsProject.instance())
        
        extent_3857 = transform.transformBoundingBox(extent)
        min_x_m = extent_3857.xMinimum()
        max_x_m = extent_3857.xMaximum()
        min_y_m = extent_3857.yMinimum()
        max_y_m = extent_3857.yMaximum()

        # Webメルカトルの地球全周サイズ (メートル)
        MAX_EXTENT = 20037508.342789244

        def meters_to_tile(x, y, z):
            """メートル座標からタイル番号(X,Y)を計算"""
            res = (2 * MAX_EXTENT) / (256 * (2 ** z))
            px = (x + MAX_EXTENT) / res
            py = (MAX_EXTENT - y) / res
            return int(px / 256), int(py / 256)

        def tile_bounds_meters(tx, ty, z):
            """タイル番号(X,Y)からメートル座標の範囲を計算"""
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
            # このズームレベルでの対象タイル範囲 (画像全体のExtentがカバーするタイル)
            t_min_x, t_max_y = meters_to_tile(min_x_m, max_y_m, z)
            t_max_x, t_min_y = meters_to_tile(max_x_m, min_y_m, z)

            z_dir = os.path.join(output_dir, str(z))
            os.makedirs(z_dir, exist_ok=True)

            for tx in range(t_min_x, t_max_x + 1):
                x_dir = os.path.join(z_dir, str(tx))
                os.makedirs(x_dir, exist_ok=True)

                for ty in range(t_max_y, t_min_y + 1):
                    # 各タイルのEPSG:3857座標範囲
                    t_b_min_x, t_b_min_y, t_b_max_x, t_b_max_y = tile_bounds_meters(tx, ty, z)

                    # 元画像内でのタイルの割合位置を計算
                    x_ratio_start = (t_b_min_x - min_x_m) / (max_x_m - min_x_m)
                    x_ratio_end = (t_b_max_x - min_x_m) / (max_x_m - min_x_m)
                    
                    # 画像座標はY軸が下向きなので逆算
                    y_ratio_start = (max_y_m - t_b_max_y) / (max_y_m - min_y_m)
                    y_ratio_end = (max_y_m - t_b_min_y) / (max_y_m - min_y_m)

                    px_start = int(x_ratio_start * src_w)
                    px_end = int(x_ratio_end * src_w)
                    py_start = int(y_ratio_start * src_h)
                    py_end = int(y_ratio_end * src_h)

                    # 画像の範囲外のタイルはスキップ
                    if px_end <= 0 or px_start >= src_w or py_end <= 0 or py_start >= src_h:
                        continue

                    # 元画像から切り出す範囲 (はみ出さないようにクリップ)
                    c_x = max(0, px_start)
                    c_y = max(0, py_start)
                    c_w = min(src_w, px_end) - c_x
                    c_h = min(src_h, py_end) - c_y

                    if c_w <= 0 or c_h <= 0:
                        continue

                    clip_rect = QRect(c_x, c_y, c_w, c_h)
                    clipped_image = source_image.copy(clip_rect)

                    # 256x256の透明なキャンバスを用意
                    tile_image = QImage(256, 256, QImage.Format_ARGB32)
                    tile_image.fill(QColor(0, 0, 0, 0))

                    tile_px_w = px_end - px_start
                    tile_px_h = py_end - py_start

                    if tile_px_w <= 0 or tile_px_h <= 0:
                        continue

                    # クリップした画像を256x256キャンバスの正しい位置にリサイズして描画
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
        QgsMessageLog.logMessage(f"[3/4] MBTiles構築中... (未実装のためスキップ)", "PMTilesExporter", Qgis.Info)

    def _convert_mbtiles_to_pmtiles(self, mbtiles_path, output_path):
        """MBTiles を PMTiles に変換（モック）"""
        QgsMessageLog.logMessage(f"[4/4] PMTilesへ変換中... (未実装のためスキップ)", "PMTilesExporter", Qgis.Info)