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
2026-10-20 に orca-ai-team の承認済み編成を引き継いだ。このプロジェクト独自の編成面談はしていない。workflow.mode=normal。
主担当: 作業を始めるチャットが計画・実装・テストを兼ねる。通常開発は Cursor / grok-4.7-high（xai）。Fast は使わない。
軽量な反復: Codex / gpt-6-luna。画像と大量資料: Gemini 3.8 Flash。難しい設計・修正: Antigravity / gemini-4-argon-medium の次に Codex / gpt-6.1-sol。
最終レビュー: Codex / gpt-6-astra の次に Cursor / claude-opus-5-5-high。それも使えなければ Antigravity / claude-opus-5-5-medium。
主担当が OpenAI のときのレビューでは Astra を使わず、Cursor Opus を第一にする。重要変更は別出自 2 モデル。
候補の正本は config/ai-team.json（plan_version 2026-10-20-v1）。

## プロジェクト固有のワークフローとスキル
最初から作らない。作業しながら、同じ手順を2回やったらスキルやworkflowにして、ここに一覧を足す。
