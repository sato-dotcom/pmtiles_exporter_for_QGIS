# -*- coding: utf-8 -*-

import os
import time
from datetime import datetime
from pathlib import Path

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtWidgets import QMenu, QFileDialog, QVBoxLayout
from qgis.core import QgsProject, QgsLayerTreeModel
from qgis.gui import QgsLayerTreeView

# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'pmtiles_exporter_dialog_base.ui'))

class PMTilesExporterDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(PMTilesExporterDialog, self).__init__(parent)
        self.setupUi(self)
        
        # 実行ボタンのテキストを変更
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setText("出力する")
        
        # --- Layer Tree を UI に埋め込む ---
        # QgsLayerTreeView のセットアップ
        self.layer_tree_view = QgsLayerTreeView(self.layer_tree_container)
        self.layer_tree_model = QgsLayerTreeModel(QgsProject.instance().layerTreeRoot())
        
        # ツリー内でチェックボックス（可視性の切り替え）を許可する
        self.layer_tree_model.setFlag(QgsLayerTreeModel.AllowNodeChangeVisibility)
        self.layer_tree_view.setModel(self.layer_tree_model)

        # プレースホルダーのレイアウトに追加
        layout = QVBoxLayout(self.layer_tree_container)
        layout.setContentsMargins(0, 0, 0, 0) # 枠線の無駄な余白を消す
        layout.addWidget(self.layer_tree_view)
        # ------------------------------------

        # シグナルの接続
        self.cmbPreset.currentIndexChanged.connect(self.on_preset_changed)
        self.btnBrowse.clicked.connect(self.on_browse_clicked)
        self.btnCandidates.clicked.connect(self.show_candidates_menu)
        
        # 出力形式の変更シグナル（拡張子自動追従のため）
        self.radio_xyz.toggled.connect(self.update_output_path_extension)
        self.radio_mbtiles.toggled.connect(self.update_output_path_extension)
        self.radio_pmtiles.toggled.connect(self.update_output_path_extension)

    def init_dialog(self):
        """ダイアログを開く際の初期化処理"""
        self.restore_settings()
        self.update_default_output_path()

    def get_output_format(self):
        """選択された出力形式を取得"""
        if self.radio_xyz.isChecked():
            return "xyz"
        elif self.radio_mbtiles.isChecked():
            return "mbtiles"
        else:
            return "pmtiles"

    def update_output_path_extension(self):
        """出力形式が変更されたら保存先パスの拡張子を合わせる"""
        current_path = self.txtOutputPath.text()
        if not current_path:
            return
            
        p = Path(current_path)
        fmt = self.get_output_format()
        
        if fmt == "xyz":
            # XYZなら拡張子を削除してフォルダパスにする
            if p.suffix in ['.pmtiles', '.mbtiles']:
                self.txtOutputPath.setText(str(p.with_suffix('')))
        elif fmt == "mbtiles":
            if p.suffix != '.mbtiles':
                self.txtOutputPath.setText(str(p.with_suffix('.mbtiles')))
        else:
            if p.suffix != '.pmtiles':
                self.txtOutputPath.setText(str(p.with_suffix('.pmtiles')))

    def restore_settings(self):
        """QSettingsから前回設定を復元"""
        settings = QSettings()
        min_zoom = settings.value("pmtiles_exporter/minzoom", 15, type=int)
        max_zoom = settings.value("pmtiles_exporter/maxzoom", 20, type=int)
        extent_mode = settings.value("pmtiles_exporter/extent_mode", "canvas", type=str)
        last_path = settings.value("pmtiles_exporter/last_output_path", "", type=str)
        
        self.spinMinZoom.setValue(min_zoom)
        self.spinMaxZoom.setValue(max_zoom)
        
        if extent_mode == "layer":
            self.radLayer.setChecked(True)
        else:
            self.radCanvas.setChecked(True)
            
        if last_path:
            self.txtOutputPath.setText(last_path)

    def save_settings(self):
        """現在の設定をQSettingsに保存"""
        settings = QSettings()
        settings.setValue("pmtiles_exporter/minzoom", self.spinMinZoom.value())
        settings.setValue("pmtiles_exporter/maxzoom", self.spinMaxZoom.value())
        
        mode = "layer" if self.radLayer.isChecked() else "canvas"
        settings.setValue("pmtiles_exporter/extent_mode", mode)
        settings.setValue("pmtiles_exporter/last_output_path", self.txtOutputPath.text())

    def on_preset_changed(self, index):
        """プリセット選択時のズーム連動"""
        text = self.cmbPreset.currentText()
        if "測量標準" in text:
            self.spinMinZoom.setValue(15)
            self.spinMaxZoom.setValue(20)
        elif "詳細確認" in text:
            self.spinMinZoom.setValue(17)
            self.spinMaxZoom.setValue(21)
        elif "ピンポイント" in text:
            self.spinMinZoom.setValue(18)
            self.spinMaxZoom.setValue(22)

    def update_default_output_path(self):
        """保存先が空の場合、初期値を自動生成"""
        if self.txtOutputPath.text().strip():
            return
            
        project_title = QgsProject.instance().title()
        if not project_title:
            project_path = QgsProject.instance().fileName()
            project_title = Path(project_path).stem if project_path else "Untitled"
                
        project_dir = QgsProject.instance().homePath() or os.path.expanduser("~")
        
        fmt = self.get_output_format()
        ext = "" if fmt == "xyz" else f".{fmt}"
        
        default_path = os.path.join(project_dir, f"{project_title}{ext}")
        self.txtOutputPath.setText(default_path)

    def show_candidates_menu(self):
        """ファイル名の候補メニューを表示"""
        project_title = QgsProject.instance().title() or Path(QgsProject.instance().fileName()).stem if QgsProject.instance().fileName() else "Untitled"
        date_str = datetime.now().strftime("%Y%m%d")
        
        first_layer_name = "layer"
        
        checked_layers = self.get_selected_layers()
        if checked_layers:
            first_layer_name = checked_layers[0].name()

        fmt = self.get_output_format()
        ext = "" if fmt == "xyz" else f".{fmt}"

        candidates = [
            f"{project_title}{ext}",
            f"overlay_{date_str}{ext}",
            f"{project_title}_{date_str}{ext}",
            f"{first_layer_name}{ext}"
        ]
        
        project_dir = QgsProject.instance().homePath() or os.path.expanduser("~")
        
        menu = QMenu(self)
        for cand in candidates:
            action = menu.addAction(cand)
            action.triggered.connect(lambda checked, c=cand: self.txtOutputPath.setText(os.path.join(project_dir, c)))
            
        menu.exec_(self.btnCandidates.mapToGlobal(self.btnCandidates.rect().bottomLeft()))

    def on_browse_clicked(self):
        """保存先選択ダイアログ"""
        project_dir = QgsProject.instance().homePath() or os.path.expanduser("~")
        fmt = self.get_output_format()
        
        if fmt == "xyz":
            file_path = QFileDialog.getExistingDirectory(self, "保存先フォルダを選択", project_dir)
        elif fmt == "mbtiles":
            file_path, _ = QFileDialog.getSaveFileName(self, "保存先を選択", project_dir, "MBTiles (*.mbtiles)")
        else:
            file_path, _ = QFileDialog.getSaveFileName(self, "保存先を選択", project_dir, "PMTiles (*.pmtiles)")
            
        if file_path:
            self.txtOutputPath.setText(file_path)

    def get_selected_layers(self):
        """チェックされたレイヤーのオブジェクトをリストで取得"""
        return QgsProject.instance().layerTreeRoot().checkedLayers()
        
    # ==========================================
    # 進捗表示・ボタン制御関連
    # ==========================================
    def init_progress(self):
        self.start_time = time.time()
        self.progressBar.setValue(0)
        self.progressBar.setVisible(True)
        self.label_progress.setVisible(True)
        self.label_progress.setText("準備中…")

    def update_progress(self, percent):
        # 残り時間計算
        if percent > 0:
            elapsed = time.time() - self.start_time
            estimated_total = elapsed / (percent / 100.0)
            remaining = estimated_total - elapsed
            m, s = divmod(int(remaining), 60)
            h, m = divmod(m, 60)
            if h > 0:
                rem_str = f"{h}時間{m}分{s}秒"
            elif m > 0:
                rem_str = f"{m}分{s}秒"
            else:
                rem_str = f"{s}秒"
        else:
            rem_str = "計算中..."

        self.progressBar.setValue(int(percent))
        self.label_progress.setText(f"{percent}% 完了（残り {rem_str}）")

    def finish_progress(self):
        self.progressBar.setValue(100)
        self.label_progress.setText("完了しました！")

    def set_export_button_enabled(self, enabled):
        """タスク実行中に多重クリックされないようボタンをロックする"""
        ok_btn = self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setEnabled(enabled)