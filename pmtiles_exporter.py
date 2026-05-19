# -*- coding: utf-8 -*-
import os
import tempfile
import shutil
from pathlib import Path

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsProject, QgsMessageLog, Qgis

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
    # 以下、仕様書 8. 出力処理の擬似コード 実装部
    # ==========================================
    def export_pmtiles(self):
        layers = self.dlg.get_selected_layers()
        if not layers:
            self.iface.messageBar().pushMessage("エラー", "レイヤーが一つも選択されていません。", level=Qgis.Critical)
            return

        extent = self._get_extent()
        min_zoom = self.dlg.spinMinZoom.value()
        max_zoom = self.dlg.spinMaxZoom.value()
        output_path = Path(self.dlg.txtOutputPath.text())

        # 高ズーム警告
        if max_zoom >= 21:
            reply = QMessageBox.warning(
                self.dlg, "高ズーム警告", 
                f"ズームレベル {max_zoom} が設定されています。\n出力に非常に長い時間がかかる可能性があります。\n続行しますか？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        tmp_dir = Path(tempfile.mkdtemp(prefix="pmtiles_exporter_"))
        
        self.iface.messageBar().pushMessage("PMTiles Exporter", f"出力を開始しました... ({output_path.name})", level=Qgis.Info)
        
        try:
            # 1. 一時フォルダへ透過PNGとしてXYZ描画
            self._render_layers_to_xyz_png(layers, extent, min_zoom, max_zoom, tmp_dir)
            
            # 2. XYZからMBTilesの構築
            mbtiles_path = tmp_dir / "temp.mbtiles"
            self._build_mbtiles_from_xyz(tmp_dir, mbtiles_path, min_zoom, max_zoom, extent)
            
            # 3. MBTilesからPMTilesへの変換
            self._convert_mbtiles_to_pmtiles(mbtiles_path, output_path)

            # 4. 成功したら設定を保存
            self.dlg.save_settings()
            self.iface.messageBar().pushMessage("PMTiles Exporter", "出力が完了しました！ 📦", level=Qgis.Success)
            
        except Exception as e:
            QgsMessageLog.logMessage(f"エラー: {str(e)}", "PMTilesExporter", Qgis.Critical)
            self.iface.messageBar().pushMessage("エラー", f"出力に失敗しました。ログを確認してください。", level=Qgis.Critical)
            
        finally:
            # 一時フォルダのお掃除
            try:
                shutil.rmtree(tmp_dir)
            except Exception as e:
                QgsMessageLog.logMessage(f"一時フォルダの削除に失敗しました: {str(e)}", "PMTilesExporter", Qgis.Warning)


    def _get_extent(self):
        """出力範囲の取得"""
        if self.dlg.radCanvas.isChecked():
            return self.iface.mapCanvas().extent()
        elif self.dlg.radLayer.isChecked():
            layers = self.dlg.get_selected_layers()
            extent = layers[0].extent()
            for layer in layers[1:]:
                extent.combineExtentWith(layer.extent())
            return extent
        else:
            return self.iface.mapCanvas().extent()

    def _render_layers_to_xyz_png(self, layers, extent, min_zoom, max_zoom, tmp_dir):
        """レイヤーを合成し、透過PNGタイルとして出力（モック）"""
        QgsMessageLog.logMessage(f"[1/3] レンダリング開始: Z{min_zoom}-{max_zoom}", "PMTilesExporter", Qgis.Info)
        # TODO: ここに QgsMapRendererCustomPainterJob 等を使用した
        # 実際のXYZタイル計算とレンダリングのロジックを組み込みます。

    def _build_mbtiles_from_xyz(self, xyz_dir, mbtiles_path, min_zoom, max_zoom, extent):
        """出力したXYZタイル群から SQLite(MBTiles) を生成（モック）"""
        QgsMessageLog.logMessage(f"[2/3] MBTiles構築中...", "PMTilesExporter", Qgis.Info)
        # TODO: Pythonの sqlite3 を用いて metadata テーブルと tiles テーブルを構築します。

    def _convert_mbtiles_to_pmtiles(self, mbtiles_path, output_path):
        """MBTiles を PMTiles に変換（モック）"""
        QgsMessageLog.logMessage(f"[3/3] PMTilesへ変換中...", "PMTilesExporter", Qgis.Info)
        # TODO: 'pmtiles' ライブラリの関数を呼び出して変換を実行します。
        # 例: 
        # import pmtiles.convert
        # pmtiles.convert.mbtiles_to_pmtiles(str(mbtiles_path), str(output_path), max_zoom)