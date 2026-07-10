## 2026-07-10 08:30 Dreamingタイム

### 今回やったこと
- README.mdが存在しなかったため新規作成した。
- SPEC.md（概要・役職・勝利条件・実行方法・ログ設計・安全設計）、run_game.py、analyze_results.py、config/agents.json、tests/ の内容を確認し、実際のCLI引数・出力構成と整合する内容にした。

### 気づいたこと
- プロジェクトはPython標準ライブラリのみで動作しており、pytest以外の外部依存がない。
- SPEC.mdのFile構成（14章）にREADME.mdが目標構成として既に記載されていたが、実ファイルは未作成の状態だった。
- Phase 1〜4はSPEC.mdの改訂履歴上「実装済み」と読み取れたが、README作成時にコード（run_game.py, analyze_results.py）側からも実行方法を裏取りして齟齬がないことを確認した。

### 改善点
- 特になし（今回はドキュメント作成のみ）。

### 次に試すとよさそうなこと
- Phase 5（記事化用ログ）着手時に、README.mdの「現在の実装状況」セクションも合わせて更新する。
- 実際に `python scripts/run_game.py --games 1` を動かした出力例をREADMEに載せると、初見の読者にとってさらに分かりやすくなりそう。

## 2026-07-10 09:20 Dreamingタイム

### 今回やったこと
- `--use-real-agents` の実運用検証を行い、Codex（CLI起動失敗・`--skip-git-repo-check`不足）、agy（`prompt_mode`のミスマッチ）、Grok（タイムアウト）のCLIエラー原因を特定し、`config/agents.json` を修正した。
- Codexが起動後もJSONを返さず聞き返す問題を見つけ、原因を追ううちに `~/.codex/AGENTS.md`（ユーザーがClaudeのDreamingタイム指示をCodexにも適用したグローバル設定）がゲームの一時ディレクトリ実行にも読み込まれていたことを発見した（ユーザーが`ORG_AGENTS.md`にリネームして対応）。
- リネーム後も残った「役職・人数・フェーズを教えてください」という聞き返しに対し、`prompts/common_player_prompt.md` ほか3ファイルに「追加質問禁止・即JSON回答」ルールを追記し、QandA.md Q61・SPEC.md 16.4章に記録した。

### 気づいたこと
- Windowsではnpmグローバルインストール製CLI（拡張子なしのシムファイル）は`subprocess.run(shell=False)`から実行できず、`codex.cmd`のように拡張子付きの実体を指定する必要がある。claude/grok/agyは`.exe`実体なのでこの問題を踏まない。
- 各AI CLIには、ユーザーが独自に設定したグローバルな運用指示（CLAUDE.md相当のAGENTS.md等）が存在し、ゲームの隔離用一時ディレクトリでの実行であっても、それらのグローバル指示がプロンプトの内容を押しのけて混入しうる。これはこのプロジェクト固有のプロンプト設計の問題ではなく、外部CLI側のグローバル設定に起因する。
- プロンプト内でどれだけ明示的に「質問するな、今すぐJSONだけ返せ」と指示しても、Codex（gpt-5.5, `codex exec`単発呼び出し）は聞き返しを完全にはやめなかった。これはモデル自体の挙動によるものと考えられ、プロンプトエンジニアリングだけでは確実な解決に至らない可能性がある。

### 改善点
- 会話の中盤で「もう十分」と決め打ちせず、ユーザーの指示（案B＝プロンプト強化）を素直に実装したうえで、効果があったかを実際に`--use-real-agents`で再検証し、効果が不十分だった事実も率直に報告できた。これは今後も維持したい姿勢。

### 次に試すとよさそうなこと
- Codexの聞き返し問題について、`config/agents.json`のCodex argsに`-c model_reasoning_effort=low`等のパラメータ変更を試す（案C）、または専用の`CODEX_HOME`（AGENTS.md/config.tomlを含まない）で完全に環境分離する案を、追加のAPIコストを踏まえてユーザーと相談のうえ検討する。
- Q61の「複数回試行しての改善率の定量評価」は未実施なので、まとまった数の`--games N --use-real-agents`を回してCodexの失敗率を数値で把握するとよい。
