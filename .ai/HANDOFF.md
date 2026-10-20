# Handoff
Updated: 2026-10-20

## 終わったこと
orca-ai-team のキットを導入した。コミットは `cf585bc4f39e9f90adb3913ed219c085c1292398`（`chore(ai-team): orca-ai-team を導入`）。共通テスト 170 件は成功。ロックの kit は `b59e6b1`。
ユーザーの指示で、この引き継ぎを origin（BRS-CloudCompare）へ push する。公式 upstream へは送らない。

## 決めたこと
push 先は origin の https://github.com/mikankun0414/BRS-CloudCompare.git 。upstream の公式 https://github.com/CloudCompare/CloudCompare.git へは送らない。
製品の GOAL は未記入。CloudCompare 本体のソースはこの導入では変えていない。
導入の直前に別コミット `cc8eb039`（`docs: add Orca custom navigation spec`）がある。このチャットではそのファイルは書いていない。

## 次の一手
このフォルダで作業するときは、承認済みの編成（TEAM.md）を引き継ぐ。公式 upstream への push はしない。
