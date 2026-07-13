# PMTiles Exporter for QGIS

QGIS のマップキャンバスに表示されているレイヤーを、そのまま PMTiles / XYZ / MBTiles として出力できる QGIS プラグインです。  

## 📍 概要
日本国内の測量業務で利用される日本平面直角座標系（1〜19系 / EPSG:6671〜6689）に対応しています。
本プラグインは、株式会社TJL による業務効率化の一環として開発されました。

---

## ✨ 主な機能

- **PMTiles 出力（推奨）**
  - 1ファイルで完結する軽量タイル形式
  - オフライン運用に最適
  - スマホでも高速表示
  - 測量支援アプリ「やまばと」で利用可能

- **XYZ タイル出力**
  - ローカルタイルとして利用可能

- **MBTiles 出力**
  - TileServerGL などのタイルサーバーで利用可能

- **出力範囲の選択**
  - 現在のキャンバス範囲
  - レイヤー結合範囲

- **ズーム範囲の指定**
  - 初期値：最小ズーム 15 / 最大ズーム 20

---

## 🗺️ 対応範囲

本プラグインは 日本国内の平面直角座標系（EPSG:6671〜6689）で作成されたレイヤの出力を前提としています。

- 日本平面直角座標系（1〜19系 / EPSG:6671〜6689）に対応  
- 海外座標系（WGS84 / EPSG:4326、Web Mercator / EPSG:3857）は非対応  
- 対象ユーザーは国内の測量・GIS 実務者を想定しています
  
### ❗ 座標系の選択 UI は存在しません

QGIS 側で設定されている座標系をそのまま使用します。 ユーザーが座標系を選択する必要はありません。 

**Note:** This plugin is intended for use in Japan only and does not support global coordinate systems.

---

## 🖥️ UI の説明

### レイヤー選択

QGIS マップキャンバスに表示されているレイヤーをそのまま出力します。


- 非表示レイヤーは出力されません  
- 選択レイヤーとは連動しません  
- QGIS の「今見えている地図」をそのままタイル化します

---

## 📌 使い方

1. QGIS で出力したいレイヤーを「表示状態」にする  
2. プラグインを開く  
3. 出力範囲を選択  
4. タイル形式を選択（PMTiles 推奨）  
5. ズーム範囲を設定  
6. 保存先フォルダを指定  
7. **OK を押すだけで出力完了**

---

## 📁 出力ファイルの利用方法

### PMTiles
- 測量支援アプリ「やまばと」で直接読み込み可能  
- PMTiles Viewer（公式）で確認可能  
- オフライン環境でも高速表示

### XYZ
- ローカルタイルとして利用可能

### MBTiles
- TileServerGL などで配信可能

---

## ⚠️ 注意点

- GitHub Pages は PMTiles の Range Request に非対応  
- **Netlify で PMTiles を配信する場合は `_headers` が必要だが、  
  本プラグインの出力ファイルを Netlify 上で正常に配信する方法は未対応（未検証）**
- QGIS のマップキャンバスに表示されていないレイヤーは出力されません

---

## 📁 プラグイン構成（ファイル一覧）

PMTiles Exporter for QGIS は以下の構成で動作しています。

pmtiles_exporter_for_QGIS/
├── __init__.py
│   └─ QGIS にプラグインを登録するためのエントリポイント。
│      classFactory() から PMTilesExporter を読み込みます。
│
├── metadata.txt
│   └─ プラグインのメタ情報（名前・作者・カテゴリ・タグなど）。
│
├── pmtiles_exporter.py
│   └─ プラグイン本体。
│      - QGIS メニュー/ツールバーへの登録
│      - ダイアログ起動
│      - PNG 出力処理（PMTiles 出力の前段階）
│      - レイヤ合成処理（QgsMapRendererCustomPainterJob）
│
├── pmtiles_exporter_dialog.py
│   └─ UI ロジック（PyQt）。
│      - レイヤツリーの埋め込み
│      - 出力範囲選択（キャンバス / レイヤ結合）
│      - ズームプリセット連動
│      - ファイル名候補生成
│      - QSettings による設定保存
│
├── pmtiles_exporter_dialog_base.ui
│   └─ Qt Designer で作成した UI 定義。
│      - レイヤ選択
│      - 出力範囲
│      - ズーム設定
│      - 保存先選択
│
├── resources.qrc
│   └─ アイコン（icon.png）を含む Qt リソース定義。
│
├── resources.py
│   └─ resources.qrc を Python に変換したもの。
│
├── icon.png
│   └─ QGIS のツールバーに表示される 32px アイコン。
│
├── README.md
│   └─ プラグインの説明書（本ファイル）。
│
├── README.html / README.txt
│   └─ 自動生成された README の別形式（GitHub 用ではない）。
│
├── pb_tool.cfg
│   └─ Plugin Builder 用の設定ファイル。
│
├── plugin_upload.py
│   └─ QGIS 公式リポジトリへアップロードするためのスクリプト。
│
└── test/
    └─ テスト用ディレクトリ（空）

---

## 👤 作者

**株式会社TJL**  
開発担当：佐藤 彰倫（Akinori Sato）

---

## 📄 ライセンス

本プラグインは **MIT License** のもとで公開されています。

