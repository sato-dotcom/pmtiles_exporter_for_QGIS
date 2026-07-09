# -*- coding: utf-8 -*-

import os
import time
from pathlib import Path

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtWidgets import QFileDialog, QVBoxLayout

from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsLayerTreeModel,
    QgsRectangle
)
from qgis.gui import QgsLayerTreeView


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'pmtiles_exporter_dialog_base.ui'))


class PMTilesExporterDialog(QtWidgets.QDialog, FORM_CLASS):
    """PMTiles Exporter ダイアログ（全国版・CRS選択UI付き）"""

    def __init__(self, parent=None):
        super(PMTilesExporterDialog, self).__init__(parent)
        self.setupUi(self)

        # ---------------------------
        # 1. レイヤーツリーの埋め込み
        # ---------------------------
        self.layerTreeView = QgsLayerTreeView()
        self.layerTreeModel = QgsLayerTreeModel(QgsProject.instance().layerTreeRoot())
        self.layerTreeView.setModel(self.layerTreeModel)

        layout = QVBoxLayout(self.layer_tree_container)
        layout.addWidget(self.layerTreeView)

        # ---------------------------
        # 2. CRS選択コンボボックスの初期化
        # ---------------------------
        self.init_crs_list()

        # ---------------------------
        # 3. タイル形式コンボボックスの初期化
        # ---------------------------
        self.cmbTileFormat.clear()
        self.cmbTileFormat.addItems(["XYZタイル", "MBTiles", "PMTiles"])

        # ---------------------------
        # 4. 保存先選択
        # ---------------------------
        self.btnBrowse.clicked.connect(self.select_output_folder)

        # ---------------------------
        # 5. 設定読み込み
        # ---------------------------
        self.load_settings()

        # ---------------------------
        # 6. OK / Cancel ボタンのシグナル接続（★ここを追記しました）
        # ---------------------------
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

    # ---------------------------------------------------------
    # CRSリストの構築
    # ---------------------------------------------------------
    def init_crs_list(self):
        crs_list = [
            ("1系 [EPSG:6669]", 6669),
            ("2系 [EPSG:6670]", 6670),
            ("3系 [EPSG:6671]", 6671),
            ("4系 [EPSG:6672]", 6672),
            ("5系 [EPSG:6673]", 6673),
            ("6系 [EPSG:6674]", 6674),
            ("7系 [EPSG:6675]", 6675),
            ("8系 [EPSG:6676]", 6676),
            ("9系 [EPSG:6677]", 6677),
            ("10系 [EPSG:6678]", 6678),
            ("11系 [EPSG:6679]", 6679),
            ("12系 [EPSG:6680]", 6680),
            ("13系 [EPSG:6681]", 6681),
            ("14系 [EPSG:6682]", 6682),
            ("15系 [EPSG:6683]", 6683),
            ("16系 [EPSG:6684]", 6684),
            ("17系 [EPSG:6685]", 6685),
            ("18系 [EPSG:6686]", 6686),
            ("19系 [EPSG:6687]", 6687),
        ]

        self.cmbCRS.clear()
        for label, epsg in crs_list:
            self.cmbCRS.addItem(label, epsg)

        self.cmbCRS.setCurrentIndex(2)  # 3系

    # ---------------------------------------------------------
    # 保存先フォルダ選択
    # ---------------------------------------------------------
    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "保存先フォルダを選択")
        if folder:
            self.txtOutputPath.setText(folder)

    # ---------------------------------------------------------
    # QGISでチェックされているレイヤーを返す
    # ---------------------------------------------------------
    def get_selected_layers(self):
        selected = []
        root = QgsProject.instance().layerTreeRoot()

        for node in root.findLayers():
            layer = node.layer()
            if layer and node.isVisible():
                selected.append(layer)

        return selected

    # ---------------------------------------------------------
    # レイヤー結合範囲
    # ---------------------------------------------------------
    def get_union_extent(self):
        layers = self.get_selected_layers()
        if not layers:
            return None

        union_extent = QgsRectangle(layers[0].extent())
        for layer in layers[1:]:
            union_extent.combineExtentWith(layer.extent())

        return union_extent

    # ---------------------------------------------------------
    # 結合範囲の CRS（最初のレイヤーの CRS）
    # ---------------------------------------------------------
    def get_extent_crs(self):
        layers = self.get_selected_layers()
        if layers:
            return layers[0].crs()

        # フォールバック
        epsg = self.cmbCRS.currentData()
        return QgsCoordinateReferenceSystem(f"EPSG:{epsg}")

    # ---------------------------------------------------------
    # 設定保存・読み込み
    # ---------------------------------------------------------
    def load_settings(self):
        s = QSettings()
        last_path = s.value("PMTilesExporter/last_output_path", "")
        if last_path:
            self.txtOutputPath.setText(last_path)

    def save_settings(self):
        s = QSettings()
        s.setValue("PMTilesExporter/last_output_path", self.txtOutputPath.text())

    # ---------------------------------------------------------
    # 進捗表示
    # ---------------------------------------------------------
    def init_progress(self):
        self.progressBar.setValue(0)
        self.progressBar.setVisible(True)
        self.label_progress.setVisible(True)
        self.label_progress.setText("準備中…")

    def update_progress(self, percent):
        self.progressBar.setValue(int(percent))
        self.label_progress.setText(f"{percent:.1f}% 完了")

    def finish_progress(self):
        self.progressBar.setValue(100)
        self.label_progress.setText("完了しました！")