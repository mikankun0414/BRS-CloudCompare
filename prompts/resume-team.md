# 主担当として再開する

AGENTS.md、現在の依頼、.ai/GOAL.md、HANDOFF.md、git status/diffを確認する。.ai/knowledge/index.mdがあれば確認し、REVIEW未対応、PLAN、TEAM、.ai/knowledge/は対象Taskに必要な箇所だけ読む。詳細な操作はprompts/team-policy.mdの該当項目を読む。
相談だけならprompts/kickoff.mdに従い回答し、Run・ボード・workerを操作しない。

- 明確な続きの依頼は再開する。同一作業内で既にユーザー承認済みのチーム編成（`approval` または `workflow.team`）を継続する場合は再確認を要しない。
- 新しく別 AI・`MAX`/上位クラスを使う前、または承認済み候補外の代替モデルへ切り替える前は、`refresh-latest` / `check-budget` で候補と残枠を示してユーザー確認を取り、Task の `approval` に記録する（自動で上位クラスに昇格しない）。
- PLAN/Taskのworkflow.modeを引き継ぐ。省略時だけnormal。rdならprompts/rd-team.mdを読み、比較条件・baseline・試行済み回数・累積時間・品質指摘・最後の良好結果を復元する。
- 「R&Dで」「通常に戻して」という切替はTask単位に記録する。再開・モデル交代・モード切替で上限をリセットせず、未確認の品質を合格にしない。
- 実作業前にversion-matched Orca guide、refresh-latest/check-budgetを実行。既存Run/Dispatchを確認してから同じRunをrun-useし、scripts/board.ps1 working -RunId <run> (Done後も同じ)。unknown/live workerへ重複起動しない。
- 選択AIが使えない時は、事前承認済みリスト内の代替なら引き継ぎ、未承認の別 AI へ移る場合は候補・残枠を示してユーザーへ確認し、理由をHANDOFFと記録へ残す。自動で上位クラスに昇格しない。
- モデル交代はsettlementを処理してから。過去のlaunch/effectiveを現在の起動成功と混同しない。
- 原本・既存出力・最後の良好結果を保持する。所有範囲と未検証項目を引き継ぎ、prompts/run-team.mdから次の作業を進める。
