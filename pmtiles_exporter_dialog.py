# -*- coding: utf-8 -*-

import os
from pathlib import Path

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtWidgets import QFileDialog

from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsRectangle
)

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'pmtiles_exporter_dialog_base.ui'))


class PMTilesExporterDialog(QtWidgets.QDialog, FORM_CLASS):
    """PMTiles Exporter ダイアログ"""

    def __init__(self, parent=None):
        super(PMTilesExporterDialog, self).__init__(parent)
        self.setupUi(self)

        # UI と Python 側の制約を明示して矛盾を防ぐ
        self.spinMinZoom.setMinimum(0)
        self.spinMinZoom.setMaximum(22)
        self.spinMaxZoom.setMinimum(0)
        self.spinMaxZoom.setMaximum(22)

        # ---------------------------
        # UIの初期値設定 (ズームレベル)
        # .ui側でも設定されていますが、念のためPython側でも明示的にセットします
        # ---------------------------
        self.spinMinZoom.setValue(15)
        self.spinMaxZoom.setValue(20)

        # ---------------------------
        # 1. タイル形式コンボボックスの初期化
        # ---------------------------
        self.cmbTileFormat.clear()
        self.cmbTileFormat.addItems(["XYZタイル", "MBTiles", "PMTiles"])

        # ---------------------------
        # 2. 保存先選択
        # ---------------------------
        self.btnBrowse.clicked.connect(self.select_output_folder)

        # ---------------------------
        # 3. 設定読み込み
        # ---------------------------
        self.load_settings()

        # ---------------------------
        # 4. OK / Cancel ボタンのシグナル接続
        # ---------------------------
        # OKボタン（accepted）はメイン処理側で制御するため、ここで勝手に閉じないように切断する
        try:
            self.buttonBox.accepted.disconnect()
        except Exception:
            pass
        
        # Cancelボタンはそのまま閉じてよい
        self.buttonBox.rejected.connect(self.reject)

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
    # レイヤー結合範囲 (指定された target_crs 上の範囲として算出)
    # ---------------------------------------------------------
    def get_union_extent(self, target_crs):
        layers = self.get_selected_layers()
        if not layers:
            return None

        project = QgsProject.instance()
        union_extent = None

        for layer in layers:
            layer_extent = layer.extent()
            if layer_extent.isEmpty():
                continue

            # レイヤーのCRSがターゲットCRS(キャンバスCRS)と異なる場合は変換する
            if layer.crs() != target_crs:
                try:
                    transform = QgsCoordinateTransform(layer.crs(), target_crs, project)
                    layer_extent = transform.transformBoundingBox(layer_extent)
                except Exception:
                    continue

            if union_extent is None:
                union_extent = QgsRectangle(layer_extent)
            else:
                union_extent.combineExtentWith(layer_extent)

        return union_extent

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

    def validate_zoom_range(self):
        min_zoom = self.spinMinZoom.value()
        max_zoom = self.spinMaxZoom.value()
        if min_zoom > max_zoom:
            self.spinMinZoom.setValue(max_zoom)
            self.spinMaxZoom.setValue(min_zoom)

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