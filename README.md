# werewolf-game

Claude / Codex / Grok / agy — 4体のCLI型AIエージェントをプレイヤーとして、**ワンナイト人狼**（襲撃なし・1晩1日で必ず決着する短期決戦ルール）を自動進行させる実験用ランナーです。

Claude Codeがゲームマスターとして進行・記録を行い、各AIプレイヤーは外部CLIプロセスとして呼び出されます。目的は、AI同士の推理・嘘・説得・投票判断を観察し、複数試合を通じてどのAIが人狼ゲームに強いかを実験的に確認することです。

詳細な仕様は [`SPEC.md`](SPEC.md) を参照してください。

## ルール概要

- プレイヤーは4人固定（人狼1・占い師1・村人2）。役職は試合ごとにランダム割り当て。
- 夜フェーズは占い師の占いのみ（人狼の襲撃なし）。
- 昼フェーズは「発言ラウンド」→「投票ラウンド」→「処刑」の順で進行。
- 勝敗は処刑結果のみで決定する（人狼を処刑できれば村人陣営勝利、それ以外は人狼陣営勝利）。
- 2日目以降の進行はなく、1試合は必ずこの流れで完結する。

## セットアップ

Python標準ライブラリのみで動作します（追加パッケージのインストールは不要）。テストの実行には [pytest](https://docs.pytest.org/) が必要です。

```bash
pip install pytest
```

実CLI（`--use-real-agents`）を使う場合は、`config/agents.json` に設定した `claude` / `codex` / `grok` / `agy` の各コマンドがPATH上で実行できる必要があります。

## 使い方

### dry-run（デフォルト、外部AIを呼ばない）

外部AIを一切呼び出さず、ダミー応答だけでゲーム進行を確認します。

```bash
python scripts/run_game.py --games 1
python scripts/run_game.py --games 1 --dry-run
```

### 実CLI接続で1試合実行

```bash
python scripts/run_game.py --games 1 --use-real-agents
```

### 複数試合実行

```bash
python scripts/run_game.py --games 10
```

### 乱数シード指定（再現性確保）

```bash
python scripts/run_game.py --games 10 --seed 1234
```

### 複数試合の結果集計

`logs/games/game_XXXX/game_state.json` を集計し、勝率やプレイヤー別・役職別成績をMarkdown/JSONで出力します。

```bash
# logs/games 配下を集計し、Markdown形式で標準出力する
python scripts/analyze_results.py

# JSON形式で標準出力する
python scripts/analyze_results.py --format json

# 指定ファイルへ保存する
python scripts/analyze_results.py --output reports/summary.md
```

## ログ・出力

試合ごとに `logs/games/game_XXXX/`（4桁連番）が作成され、以下を保存します。

```text
logs/games/game_0001/
├─ game_state.json   # 役職・進行状況・勝敗などの内部状態
├─ public_log.md      # 全プレイヤーに公開される発言・投票ログ
├─ results.md         # 試合結果のサマリー
└─ raw/               # 不正応答など、フォールバック時の生応答を保存
```

`logs/` および `reports/` はGit管理対象外です（`.gitignore` 参照）。

## プロジェクト構成

```text
.
├─ SPEC.md            # 仕様書
├─ USECASE.md / SEQUENCE.md / CLASS.md / TESTCASE.md  # 設計ドキュメント
├─ QandA.md           # 仕様検討時の論点整理
├─ config/
│  └─ agents.json     # 各AIプレイヤーの呼び出しコマンド定義
├─ prompts/           # 役職別・フェーズ別プロンプト
├─ scripts/
│  ├─ run_game.py         # ゲーム実行エントリポイント
│  ├─ analyze_results.py  # 複数試合の集計スクリプト
│  ├─ agents.py           # プレイヤー呼び出し・プロンプト構築
│  ├─ game_rules.py       # ゲーム進行エンジン
│  ├─ json_utils.py       # AI出力JSONの検証
│  ├─ log_writer.py       # ログ出力
│  ├─ models.py           # データクラス定義
│  └─ random_utils.py     # シード付き乱数生成
└─ tests/             # pytestによるユニットテスト
```

## テスト

```bash
pytest tests/
```

## 安全設計（概要）

- 標準動作は外部AIを呼ばない dry-run。実CLI呼び出しは `--use-real-agents` を明示指定した場合のみ。
- AIプレイヤーにはゲーム外のファイル操作・シェルコマンド実行を許可しない。
- `game_state.json` など内部状態ファイルを直接読み取らせない。
- プロンプトインジェクション対策・タイムアウト・不正応答時のフォールバックを実装済み。

詳細は [`SPEC.md`](SPEC.md) の「16. 安全設計」を参照してください。

## 現在の実装状況

- Phase 1: ゲームエンジン（dry-run） — 実装済み
- Phase 2: プロンプト整備 — 実装済み
- Phase 3: 実CLI接続 — 実装済み
- Phase 4: 複数試合集計 — 実装済み
- Phase 5: 記事化用ログ — 未着手

詳細は [`SPEC.md`](SPEC.md) 冒頭の改訂履歴を参照してください。
