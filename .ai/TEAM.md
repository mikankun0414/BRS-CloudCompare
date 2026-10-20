# Team
共通運用の正本はAGENTSの共通ブロックとprompts/。以下はプロジェクト固有の編成記録。
主担当がCoordinator・計画・実装・テストを兼ねる。必要な時だけ独立レビュー/品質担当を呼ぶ。
Coordinatorだけが共有PLAN/HANDOFF/REVIEWを編集する。
Coderは指定したファイルだけを編集。TesterとReviewer A/BとJudgeは原則reportのみ。
同一ファイルに複数writerを割り当てない。独立レビューは相手の結果を見る前にreportを提出する。
候補と有効化はconfig/ai-team.json。catalog/認証/quotaと起動成功を区別する。
通常は主担当→テスト→別出自Reviewer。重要変更は独立2モデル。rdの品質再評価は別工程。
同種失敗1回は同クラス、2回はSTRONG、STRONG失敗でSol highを検討。MAXは明示した根拠が必要。
Jevは助言。キーなし・通信不可・低confidenceはCoordinatorが判定。
外部plannerは複雑な設計を委任する時だけprompts/plan-team.mdを使う。

## 今回の編成
主担当と必要な役・代替だけ初回に選び、承認済み編成を再開時に引き継ぐ。役 / agent / model / effort / 出自 / 理由。未記入。

## プロジェクト固有のワークフローとスキル
最初から作らない。作業しながら、同じ手順を2回やったらスキルやworkflowにして、ここに一覧を足す。
