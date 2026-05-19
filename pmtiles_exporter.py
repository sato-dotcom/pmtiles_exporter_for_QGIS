# -*- coding: utf-8 -*-
import os
import tempfile
import shutil
from pathlib import Path

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QSize
from qgis.PyQt.QtGui import QIcon, QImage, QPainter
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (
    QgsProject, 
    QgsMessageLog, 
    Qgis,
    QgsMapSettings,
    QgsMapRendererCustomPainterJob
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

        # ダイアログを開く前に設定やレイヤー一覧を初期化
        self.dlg.init_dialog()
        self.dlg.show()
        
        result = self.dlg.exec_()
        if result:
            self.export_pmtiles()

    # ==========================================
    # 以下、出力処理 実装部
    # ==========================================
    def export_pmtiles(self):
        """
        ダイアログの「PMTiles を出力する」ボタン（OKボタン）が押されたときの処理。
        現在はステップ1として、単一のPNG画像を出力する処理を実行する。
        """
        output_path_str = self.dlg.txtOutputPath.text()
        if not output_path_str:
            self.iface.messageBar().pushMessage("エラー", "保存先が指定されていません。", level=Qgis.Critical)
            return

        # UIの拡張子を .png に置換
        png_path = output_path_str.replace(".pmtiles", ".png")
        extent = self._get_extent()

        self.iface.messageBar().pushMessage("PMTiles Exporter", f"PNG出力を開始しました... ({Path(png_path).name})", level=Qgis.Info)

        try:
            # 1. 透過PNGとして出力
            self.export_layers_to_png(png_path, extent=extent)
            
            # 成功したら設定を保存
            self.dlg.save_settings()
            self.iface.messageBar().pushMessage("PMTiles Exporter", f"PNG 出力完了: {png_path}", level=Qgis.Success)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"エラー: {str(e)}", "PMTilesExporter", Qgis.Critical)
            self.iface.messageBar().pushMessage("エラー", f"出力に失敗しました。ログを確認してください。\n{e}", level=Qgis.Critical)

    def export_layers_to_png(self, output_path, extent=None, width=2048, height=2048):
        """
        QGIS の現在のレイヤーを合成して PNG を出力する最小実装。
        """
        # レイヤーツリーの描画順（上から下）を取得
        all_layers = [layer for layer in QgsProject.instance().layerTreeRoot().layerOrder()]
        
        # UIでチェックされているレイヤーのみに絞り込む（順番は描画順を維持）
        selected_layers = self.dlg.get_selected_layers()
        layers = [layer for layer in all_layers if layer in selected_layers]

        if not layers:
            raise Exception("出力対象のレイヤーがありません。")

        settings = QgsMapSettings()
        settings.setLayers(layers)

        if extent is None:
            canvas = self.iface.mapCanvas()
            extent = canvas.extent()

        settings.setExtent(extent)
        settings.setOutputSize(QSize(width, height))

        # 透過背景の画像を作成
        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(0) # 0は完全な透明

        painter = QPainter(image)
        job = QgsMapRendererCustomPainterJob(settings, painter)
        job.start()
        job.waitForFinished()
        painter.end()

        image.save(str(output_path), "PNG")
        return True

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
    # 今後実装予定のモック関数群
    # ==========================================
    def _render_layers_to_xyz_png(self, layers, extent, min_zoom, max_zoom, tmp_dir):
        """レイヤーを合成し、透過PNGタイルとして出力（モック）"""
        QgsMessageLog.logMessage(f"[1/3] レンダリング開始: Z{min_zoom}-{max_zoom}", "PMTilesExporter", Qgis.Info)

    def _build_mbtiles_from_xyz(self, xyz_dir, mbtiles_path, min_zoom, max_zoom, extent):
        """出力したXYZタイル群から SQLite(MBTiles) を生成（モック）"""
        QgsMessageLog.logMessage(f"[2/3] MBTiles構築中...", "PMTilesExporter", Qgis.Info)

    def _convert_mbtiles_to_pmtiles(self, mbtiles_path, output_path):
        """MBTiles を PMTiles に変換（モック）"""
        QgsMessageLog.logMessage(f"[3/3] PMTilesへ変換中...", "PMTilesExporter", Qgis.Info)