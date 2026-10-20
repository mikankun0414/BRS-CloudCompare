# CloudCompare DCC風カメラナビゲーション改造仕様書 (Orca Project)

## 1. プロジェクト概要・目的
CloudCompareの標準カメラ操作はCAD/点群検査向けの仮想トラックボール（回転時に画面が傾く）や特殊な軸ロック（上下を向けない）となっています。  
本プロジェクトでは、**Blender や 3ds Max などのDCC（Digital Content Creation）ツールと同様の直感的なカメラ操作（真のターンテーブル・画面中心回転・ウォークスルー）** をCloudCompareに組み込むことを目的とします。

---

## 2. 実現したい機能・要件（やりたいこと）

### ① 真のターンテーブル回転（DCC風オービット）
* **左右ドラッグ**:
  * ワールドZ軸（垂直軸）を中心としたスムーズな360度水平回転（ヨー）。
* **上下ドラッグ**:
  * 視点を見上げる・見下ろす仰俯角回転（ピッチ：-89°〜+89°）。
* **ロール回転の完全排除**:
  * 画面が斜めに傾いてしまう（首をかしげる）ロール角を常に 0 に固定し、水平線を常に維持する。
* **画面中心での回転**:
  * 画面の中心（ビューポート中央）にあるピボットポイントを基準として滑らかに旋回。

### ② DCC準拠のマウス操作体系
* **中ボタンドラッグ**: ビューのターンテーブル回転（Blender標準）
* **Shift + 中ボタンドラッグ**: ビューのパン（平行移動）
* **マウスホイール**: ズーム（拡大・縮小）
* *(従来の左ドラッグ回転・右ドラッグパンもオプションとして維持)*

### ③ ウォークスルーモード（FPSスタイル一人称ナビゲーション）
* キー入力による点群内部の歩行・飛行移動：
  * **W / S**: 前進 / 後退
  * **A / D**: 左移動 / 右移動
  * **Q / E**: 上昇 / 下降
* マウス移動による視線方向の見回し（FPSマウスルック）

---

## 3. 技術仕様と改造対象

* **リポジトリパス**: `D:\CloudCompare`
* **対象コード**:
  * `libs/qCC_glWindow/include/ccGLWindowInterface.h`
  * `libs/qCC_glWindow/src/ccGLWindowInterface.cpp`
    * `processMouseMoveEvent`（回転・パンの計算処理）
    * `processMousePressEvent`（中ボタンドラッグの受付）
    * `processWheelEvent`（ズーム）
    * `processKeyPressEvent`（WASDウォークスルー）

---

## 4. 開発・実装ステップ（TODO）

- [ ] **Step 1: Qt6ビルド環境の準備**
  - Pythonの `aqtinstall` 等を利用して `D:\Qt` に Qt 6 (msvc2022_64) をセットアップ
- [ ] **Step 2: ターンテーブル回転ロジックの実装**
  - `ccGLWindowInterface.cpp` の回転計算部分をオイラー角ベース（Yaw + Pitch、Roll=0固定）に変更
- [ ] **Step 3: DCCマウス操作（中ボタンドラッグ）の組み込み**
  - 中ボタンおよび Shift+中ボタン イベントの処理を追加
- [ ] **Step 4: CMake設定とVisual Studioソリューション生成**
  - `cmake -B build -S . -DCMAKE_PREFIX_PATH="D:\Qt\..."`
- [ ] **Step 5: ビルド＆動作検証**
  - Visual Studio 2022 でビルドし、Blender風に画面中心・縦軸固定＋上下チルトで動くことを確認
- [ ] **Step 6: （拡張）WASDウォークスルーモードの実装**
