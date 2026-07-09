# TESTCASE.md

## Project: AI Multi-Agent Werewolf Game (One Night Werewolf)

Version: 0.1-draft  
Based on: `CLASS.md` / `SPEC.md` v0.6-draft / `SEQUENCE.md` / `USECASE.md`  
Primary target: Phase 1 dry-run implementation

---

## 1. 目的・方針

`CLASS.md`のクラス責務に対するPhase 1の単体・結合・E2Eテストを定義する。Phase 3専用の`AgentInvoker`と`PromptBuilder`は将来テストの観点だけを記載する。

- Unit: 引数検証、乱数、dry-run応答、JSON検証、フォールバック、処刑・勝敗判定
- Integration: `GameEngine`、`PlayerAgent`、`LogWriter`を一時ディレクトリ上で結合
- E2E: `scripts/run_game.py`をsubprocessで起動し、終了コードと生成物を検証
- Markdownは必要情報・順序・秘密情報の不在を検証し、未定義の装飾まで全面一致させない
- 標準プレイヤー順はClaude→Codex→Grok→agyとする
- テストフレームワークはpytestとし、`tests/`配下へ責務別の`test_*.py`を置く
- ファイルテストはpytestの`tmp_path`配下を使い、実リポジトリの`logs/`を汚染しない

---

## 2. Runner・CLI

| ID | 条件・操作 | 期待結果 |
|---|---|---|
| TC-RUN-001 | `--games 1 --dry-run` | 0終了、DRY_RUNで1試合実行 |
| TC-RUN-002 | `--games 1` | 0終了、デフォルトDRY_RUN |
| TC-RUN-003 | `--games 1 --use-real-agents` | REAL_AGENTSと判定（Phase 1では外部呼出前まで） |
| TC-RUN-004 | `--dry-run --use-real-agents` | 設定読込・RNG初期化・ディレクトリ作成前に非0終了 |
| TC-RUN-005 | `--games 0` | 副作用なしで非0終了 |
| TC-RUN-006 | `--games -1` | 副作用なしで非0終了 |
| TC-RUN-007 | `--games abc` | 副作用なしで非0終了 |
| TC-RUN-008 | 未知オプション | 副作用なしで非0終了 |
| TC-RUN-009 | `--games 3 --seed 1234` | RNGを1回だけ生成し、同じインスタンスを3試合で使用 |
| TC-RUN-010 | 既存最大`game_0007`、3試合 | `start_game_id=8`、ループ内で0008〜0010を作成 |

---

## 3. ConfigLoader・RandomGenerator

| ID | 対象・操作 | 期待結果 |
|---|---|---|
| TC-CFG-001 | 標準設定読込 | 4件を定義順のまま返す |
| TC-CFG-002 | 各設定 | name/command/args/prompt_modeを保持 |
| TC-CFG-003 | JSON構文不正 | 設定エラー、試合ディレクトリ作成なし |
| TC-CFG-004 | 必須項目欠落・4名以外・空command・非配列args・不正prompt_mode | 設定読込時にエラー。ログディレクトリ作成なし |
| TC-RNG-001 | 同じseed・同じ呼出列 | 全選択結果が一致 |
| TC-RNG-002 | 役職shuffle | werewolf×1、seer×1、villager×2を保持 |
| TC-RNG-003 | 役職割当 | shuffle後の役職を設定定義順に割当 |
| TC-RNG-004 | 候補選択 | 候補外を返さず、候補順を並べ替えない |
| TC-RNG-005 | 1試合dry-run | shuffle→占い→4人の投票→必要時のみ同票処刑の順で消費 |
| TC-RNG-006 | 2試合 | 第2試合で再seedせず第1試合の続きから消費 |
| TC-RNG-007 | 同一初期状態・同一seedで2回 | game_id等を除くゲーム内容が一致 |
| TC-RNG-008 | seed=1234代表シナリオ | Python標準random.Randomによる役職・占い・投票・処刑結果が回帰期待値と一致 |

---

## 4. DryRunAgent・JsonValidator

| ID | 対象・入力 | 期待結果 |
|---|---|---|
| TC-DRY-001 | Codexの発言 | `speech="（dry-run）Codexの発言です。"`、`reason="（dry-run）固定テンプレート発言です。"` |
| TC-DRY-002 | 占い | targetは自分以外、reasonは固定文 |
| TC-DRY-003 | 投票 | voteは自分以外、reasonは固定文 |
| TC-VAL-001 | 正常speech JSON | ok=true |
| TC-VAL-002 | 正常vote JSON | 自分以外の実在名ならok=true |
| TC-VAL-003 | 正常night JSON | 占い師以外ならok=true |
| TC-VAL-010 | 不正JSON | syntax |
| TC-VAL-011 | コードフェンス付き | syntax |
| TC-VAL-012 | JSON前後にテキスト | syntax |
| TC-VAL-013 | 複数JSON・配列 | syntax |
| TC-VAL-020 | 必須キー欠落 | semantic |
| TC-VAL-021 | 定義外キー | semantic |
| TC-VAL-022 | 空文字/null/型不一致 | semantic |
| TC-VAL-023 | 存在しないプレイヤー | semantic |
| TC-VAL-024 | 自分への投票 | semantic |
| TC-VAL-025 | 自分自身を占う | semantic |
| TC-VAL-026 | phaseと異なるスキーマ | semantic |

---

## 5. FallbackHandler・ゲームルール

| ID | 条件 | 期待結果 |
|---|---|---|
| TC-FBK-001 | speech失敗 | `"発言に失敗しました。"`、RNG消費なし |
| TC-FBK-002 | vote失敗 | 定義順から自分を除いた候補を共有RNGで選択 |
| TC-FBK-003 | night失敗 | 定義順から占い師を除いた候補を共有RNGで選択 |
| TC-FBK-004 | 複数エラー | raw連番を01から増やし、ゲーム継続 |
| TC-GME-001 | 人狼を占う | result=`werewolf` |
| TC-GME-002 | 非人狼を占う | result=`human` |
| TC-GME-003 | 最多得票1名 | そのプレイヤーを処刑し、処刑用RNGを消費しない |
| TC-GME-004 | 最多得票が同票 | 同票者を定義順に並べ、共有RNGで選択 |
| TC-GME-005 | 人狼を処刑 | winner=`villager` |
| TC-GME-006 | 人狼以外を処刑 | winner=`werewolf` |
| TC-GME-007 | 発言ラウンド | 定義順。後続者は先行発言を参照可能 |
| TC-GME-008 | 投票ラウンド | 全員へ同じ凍結ログを渡し、途中票を非公開 |
| TC-GME-009 | 状態遷移 | setup→night→speech→vote→finished |
| TC-GME-010 | 1試合 | 夜→発言→投票→処刑→勝敗で完了。襲撃・2日目なし |
| TC-GME-011 | 2試合 | 役職・占い・ログ・票・処刑・勝敗・状態を非継承 |

---

## 6. LogWriter・ファイル

| ID | 条件・操作 | 期待結果 |
|---|---|---|
| TC-LOG-001 | gamesディレクトリが空 | next_game_id=1 |
| TC-LOG-002 | game_0002とgame_0010あり | next_game_id=11 |
| TC-LOG-003 | 無関係な名前あり | 採番対象外 |
| TC-LOG-004 | 1試合開始 | game_XXXXと3ファイルを作成 |
| TC-LOG-005 | 完了状態 | 有効JSON、phase=finished、executed/winnerあり |
| TC-LOG-006 | public_log | 発言・全投票・処刑・勝敗あり。役職一覧・秘密占いなし |
| TC-LOG-007 | results | 役職・発言・投票・占い・勝敗・エラーあり |
| TC-LOG-008 | 1件目の不正応答 | `raw/01_{phase}_{player}_{error}.txt`へ生応答保存 |
| TC-LOG-009 | 複数エラー | 上書きせず発生順連番 |
| TC-LOG-010 | Phase 1 | ルート直下に3状態ファイルを作らない |
| TC-LOG-011 | 既存試合あり | 上書きしない |

---

## 7. E2E・障害

| ID | 条件・操作 | 期待結果 |
|---|---|---|
| TC-E2E-001 | `python scripts/run_game.py --games 1` | 0終了、外部CLIなし、1試合ログ生成 |
| TC-E2E-002 | `--games 1 --dry-run` | TC-E2E-001と同じモード・進行 |
| TC-E2E-003 | `--games 10 --dry-run --seed 1234` | 連続10ディレクトリ、全試合完了 |
| TC-E2E-004 | 同じ初期状態でE2E-003を再実行 | ゲーム内容を再現 |
| TC-E2E-005 | 正常dry-run | 外部CLI・rawエラーなし、全ダミーJSONが検証通過 |
| TC-IO-001 | 書込失敗を注入 | 非0終了、残り試合を実行しない |
| TC-IO-002 | 第2試合で失敗 | 第1試合を変更しない |
| TC-IO-003 | 書込途中で失敗 | 不完全game_XXXXを診断用に残す |

---

## 8. Phase 3向け保留観点

- 一時ディレクトリ、`subprocess.run(shell=False)`、prompt_modeのarg/stdin分岐
- timeout/CLI異常終了のraw保存とフォールバック
- 呼出終了後の一時ディレクトリ削除
- 同一seedかつ同一乱数呼出列の場合だけエンジン内選択が一致
- 外部AIの発言・投票・応答成否・試合結果全体は再現対象外

---

## 9. 実装開始判定

Q42〜Q48は確定済み。pytest、共有RNGと依存注入、`tmp_path`、代表seed回帰、内容ベースのMarkdown検証、agents設定検証を用いてPhase 1テストを実装する。
