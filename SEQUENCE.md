# SEQUENCE.md

## Project: AI Multi-Agent Werewolf Game (One Night Werewolf)

Version: 0.2-draft
Based on: `SPEC.md` v0.9-draft / `USECASE.md` / `QandA.md`
Primary target: Phase 1 dry-run and Phase 3 AgentInvoker implementation

---

## 1. 目的

本書は、Phase 1 dry-run実装において、以下のコマンドがどの順序で処理されるべきかを明確にする。

```bash
python scripts/run_game.py --games 1 --dry-run
```

また、`--games N` による複数試合ループ、JSON検証・フォールバック、ログ保存、Phase 3 real-CLI接続時の参考シーケンスも併せて記載する。

---

## 2. 前提

### 2.1 参照仕様

- `SPEC.md` v0.5-draft
- `USECASE.md`
- `QandA.md`

### 2.2 対象範囲

本書の主対象は Phase 1 dry-run である。

Phase 1では、外部AI CLIを呼び出さない。  
Claude / Codex / Grok / agy の応答は、システム内部のdry-runダミー応答ロジックが生成する。

Phase 3 real-CLI接続は、参考シーケンスとして別章に記載する。

### 2.3 USECASE.mdとの対応

| UC | 概要 | 本書での扱い |
|---|---|---|
| UC-01 | dry-runで1試合実行する | 主対象 |
| UC-02 | 実CLIで1試合実行する | Phase 3参考 |
| UC-03 | 複数試合を連続実行する | Phase 1ループとして扱う |
| UC-04 | `--seed` により再現性を確保する | Phase 1では完全再現。Phase 3では同一乱数呼び出し列に限りエンジン内選択を再現 |
| UC-06 | 夜フェーズを実行する | dry-runでは内部ロジックが占いを生成 |
| UC-07 | 昼の発言ラウンドを実行する | dry-runでは固定テンプレート発言 |
| UC-08 | 投票ラウンドを実行する | dry-runではシード付き乱数で投票 |
| UC-09 | 処刑・勝敗判定を行う | Phase 1で実装対象 |
| UC-11 | 不正応答を検証しフォールバックする | Phase 1では syntax/semantic、Phase 3では timeout/cli も対象 |

---

## 3. 主要コンポーネント

```text
Operator
  運用者。run_game.py を実行する。

run_game.py
  CLI引数解析、モード判定、試合ループ全体を担当する。

GameEngine
  役職割当、夜フェーズ、昼フェーズ、投票、処刑、勝敗判定を担当する。

DryRunAgent
  Phase 1 dry-run時に、AIプレイヤーの代わりに正常JSONを生成する内部ロジック。

AgentInvoker
  Phase 3 real-CLI時に外部AI CLIを呼び出すコンポーネント。Phase 1では使用しない。

JsonValidator
  AI応答またはdry-run応答のJSON構文・意味検証を担当する。

FallbackHandler
  JSON不正、CLI失敗、タイムアウト時に代替行動を決定する。

LogWriter
  game_state.json、public_log.md、results.md、raw/ を保存する。

RandomGenerator
  run_game.py起動時に1つだけ初期化され、全試合で使い続ける乱数生成器。
```

---

## 4. Phase 1 dry-run 全体シーケンス

対象コマンド:

```bash
python scripts/run_game.py --games 1 --dry-run
```

```mermaid
sequenceDiagram
    autonumber
    actor Operator as 運用者
    participant Runner as run_game.py
    participant Config as ConfigLoader
    participant RNG as RandomGenerator
    participant Engine as GameEngine
    participant Dry as DryRunAgent
    participant Validator as JsonValidator
    participant Fallback as FallbackHandler
    participant Log as LogWriter

    Operator->>Runner: python scripts/run_game.py --games 1 --dry-run
    Runner->>Runner: CLI引数解析
    Note over Runner: --games は1以上の整数であることを検証する（argparse等）。<br/>不正な場合、設定読込・乱数初期化・ディレクトリ作成の前に非0終了する（QandA Q40）。
    Runner->>Runner: モード判定
    Note over Runner: --dry-runあり、またはフラグなしなら DRY-RUN<br/>--use-real-agents のみ REAL-AGENTS<br/>--dry-run と --use-real-agents を同時指定した場合は、<br/>設定読込・乱数初期化・ディレクトリ作成の前にエラー終了する（相互排他。QandA Q36）。

    Runner->>Config: config/agents.json 読み込み
    Config-->>Runner: プレイヤー定義順 Claude -> Codex -> Grok -> agy

    Runner->>RNG: 起動時に乱数生成器を1つ初期化
    Note over RNG: --seed指定時は random.Random(seed)<br/>seed未指定時は非決定的

    Runner->>Log: logs/games/ 既存最大番号を確認
    Log-->>Runner: start_game_id = 既存最大番号 + 1

    loop i = 0..(games-1)（game_id = start_game_id + i）
        Runner->>Log: logs/games/game_XXXX/ を作成する（QandA Q35: 試合ごとにループ内で作成）
        Runner->>Engine: 新規試合を開始(game_id, players, RNG)
        Engine->>Log: phase=setup に更新して game_state.json 初期化
        Engine->>Log: public_log.md 初期化
        Engine->>Log: results.md 初期化

        Engine->>RNG: 役職リストをシャッフル
        RNG-->>Engine: shuffled roles
        Engine->>Engine: agents.json定義順に役職割当
        Engine->>Log: phase=night に更新して game_state.json 保存

        Engine->>Dry: 夜フェーズ: 占い師の占いJSON生成
        Dry->>RNG: 占い師以外の候補から占い先を選択
        RNG-->>Dry: target
        Dry-->>Engine: {"target":"...","reason":"..."}
        Engine->>Validator: night_seer JSON検証
        alt valid
            Validator-->>Engine: OK
            Engine->>Engine: seer_result を作成
            Note over Engine: result は werewolf / human の二値
        else invalid
            Validator-->>Engine: syntax/semantic error
            Engine->>Log: raw/{seq}_night_{player}_{error}.txt 保存
            Engine->>Fallback: 占い先フォールバック
            Fallback->>RNG: 候補から占い先を選択
            RNG-->>Fallback: target
            Fallback-->>Engine: fallback target
            Engine->>Engine: seer_result を作成
            Engine->>Log: results.md にエラー記録
        end
        Engine->>Log: seer_result を設定し、phase=speech に更新して保存

        loop players in agents.json order
            Engine->>Dry: 発言JSON生成(player)
            Dry-->>Engine: {"speech":"（dry-run）{player}の発言です。","reason":"（dry-run）固定テンプレート発言です。"}
            Note over Dry,Engine: reasonも必須キーのため省略しない（QandA Q34。省略すると全発言が必須キー欠落で検証NGになる）
            Engine->>Validator: speech JSON検証
            alt valid
                Validator-->>Engine: OK
                Engine->>Log: public_log.md に発言を逐次追記
            else invalid
                Validator-->>Engine: syntax/semantic error
                Engine->>Log: raw/{seq}_speech_{player}_{error}.txt 保存
                Engine->>Fallback: 発言フォールバック
                Fallback-->>Engine: 「発言に失敗しました。」
                Engine->>Log: public_log.md にフォールバック発言を追記
                Engine->>Log: results.md にエラー記録
            end
        end

        Engine->>Log: 発言ラウンド終了時点の public_log を確定
        Engine->>Log: phase=vote に更新して game_state.json 保存
        Note over Engine,Log: 投票ラウンドでは全員に同一の公開ログを使う

        loop players in agents.json order
            Engine->>Dry: 投票JSON生成(player, frozen_public_log)
            Dry->>RNG: 自分以外の候補から投票先を選択
            RNG-->>Dry: vote target
            Dry-->>Engine: {"vote":"...","reason":"（dry-run）シード付きランダムで選択しました。"}
            Engine->>Validator: vote JSON検証
            alt valid
                Validator-->>Engine: OK
                Engine->>Engine: 投票を内部収集
            else invalid
                Validator-->>Engine: syntax/semantic error
                Engine->>Log: raw/{seq}_vote_{player}_{error}.txt 保存
                Engine->>Fallback: 投票先フォールバック
                Fallback->>RNG: 自分以外の候補から投票先を選択
                RNG-->>Fallback: vote target
                Fallback-->>Engine: fallback vote
                Engine->>Engine: フォールバック投票を内部収集
                Engine->>Log: results.md にエラー記録
            end
        end

        Engine->>Log: public_log.md に投票結果を一括追記
        Engine->>Engine: 最多得票者を算出
        alt 最多得票者が1名
            Engine->>Engine: executed = 最多得票者
        else 同票
            Engine->>RNG: 同票対象から処刑対象を選択
            RNG-->>Engine: executed
        end

        Engine->>Engine: 勝敗判定
        Note over Engine: executed が人狼なら winner = villager<br/>それ以外なら winner = werewolf

        Engine->>Log: 処刑・勝敗判定完了後、phase=finished に更新して保存
        Engine->>Log: public_log.md 保存(処刑・勝敗)
        Engine->>Log: results.md 保存(役職、占い、投票、勝敗、エラー)
    end

    Runner-->>Operator: 実行結果を表示
```

---

## 5. `--games N` 複数試合ループ

対象ユースケース: UC-03 / UC-04

```mermaid
sequenceDiagram
    autonumber
    actor Operator as 運用者
    participant Runner as run_game.py
    participant RNG as RandomGenerator
    participant Log as LogWriter
    participant Engine as GameEngine

    Operator->>Runner: python scripts/run_game.py --games N --dry-run --seed 1234
    Runner->>RNG: random.Random(1234) を1つだけ初期化
    Runner->>Log: logs/games/ 既存最大 game_XXXX を確認
    Log-->>Runner: start_game_id = max + 1

    loop i = 0 to N-1
        Runner->>Log: logs/games/game_XXXX/（game_id=start_game_id+i）を作成する
        Runner->>Engine: run_one_game(game_id=start_game_id+i, RNG)
        Note over Engine: 各試合の状態は完全に独立<br/>前試合の役職・占い・発言・投票・勝敗は引き継がない
        Engine->>RNG: 同じRNGインスタンスを継続利用
        Engine->>Log: logs/games/game_XXXX/ に試合ログ保存
    end

    Runner-->>Operator: N試合完了
```

### 5.1 複数試合時のルール

- 試合ディレクトリは `logs/games/` の既存最大番号 + 1 から採番し、各試合の開始直前にループ内で1つずつ作成する（QandA Q35）。
- `--games N` は連続したN個のディレクトリを作成する。
- 各試合は完全に独立する。
- 乱数生成器は `run_game.py` 起動時に1つだけ作り、全試合で使い続ける。
- 1試合内でフォールバックが発生しても、N試合ループ全体は継続する。
- 致命的なファイル書き込みエラーなど、試合結果を保存できない場合は実行全体を非0終了コードで停止する。既に完了した試合のディレクトリは変更しない。書き込みに失敗した試合の不完全なディレクトリは、診断用にそのまま残し、削除しない（QandA Q38）。

---

## 6. 乱数消費順

対象ユースケース: UC-04

`--seed` 指定時、Phase 1 dry-runでは同一シード・同一設定で試合結果を完全再現する。

1試合内の乱数消費順は以下で固定する。

```mermaid
sequenceDiagram
    autonumber
    participant Engine as GameEngine
    participant RNG as RandomGenerator

    Engine->>RNG: 1. 役職リストをシャッフル
    RNG-->>Engine: roles
    Engine->>RNG: 2. 夜フェーズ dry-run占い先を選択
    RNG-->>Engine: seer target
    Engine->>RNG: 3. Claude のdry-run投票先を選択
    RNG-->>Engine: vote target
    Engine->>RNG: 4. Codex のdry-run投票先を選択
    RNG-->>Engine: vote target
    Engine->>RNG: 5. Grok のdry-run投票先を選択
    RNG-->>Engine: vote target
    Engine->>RNG: 6. agy のdry-run投票先を選択
    RNG-->>Engine: vote target
    opt 同票時のみ
        Engine->>RNG: 7. 同票処刑対象を選択
        RNG-->>Engine: executed
    end
```

### 6.1 候補リスト順

候補リストはすべて `config/agents.json` の定義順を使う。

初期設定:

```text
Claude -> Codex -> Grok -> agy
```

名前のソート順は使わない。

### 6.2 Phase 3 real-CLI時の再現性

Phase 3 real-CLI時は、外部AIの自然言語応答自体は再現対象外とする。

同一seedかつ同一の乱数呼び出し列である場合に、以下のエンジン内ランダム選択結果を再現できる。

- 役職割当
- フォールバック時の占い先・投票先
- 同票時の処刑対象

実CLIの正常応答時には、占い先・投票先はAI応答に従うため、dry-run時のように常に乱数を消費するとは限らない。さらに、外部AI応答の成否（正常／構文エラー／内容エラー／タイムアウト／CLI異常終了）によってフォールバックの発生有無・回数・同票の発生有無が変わるため、乱数呼び出しの回数・順序自体が試合ごとに変動しうる。外部AIの発言・投票・応答成否および試合結果全体は再現対象外とする。したがってPhase 3での`--seed`の保証は、「同一seedかつ同一の乱数呼び出し列であれば、各エンジン内ランダム選択の結果は再現される」という決定性だけに限定する（QandA Q39）。

---

## 7. JSON検証・フォールバックシーケンス

対象ユースケース: UC-11

Phase 1では `syntax` / `semantic` を主対象とする。  
Phase 3では `timeout` / `cli` も対象に追加する。

```mermaid
sequenceDiagram
    autonumber
    participant Engine as GameEngine
    participant Source as DryRunAgent or AgentInvoker
    participant Validator as JsonValidator
    participant Fallback as FallbackHandler
    participant RNG as RandomGenerator
    participant Log as LogWriter

    Engine->>Source: 行動要求(speech / vote / night)
    Source-->>Engine: raw response
    Engine->>Validator: JSON構文検証

    alt JSON構文エラー
        Validator-->>Engine: syntax error
        Engine->>Log: raw/{seq}_{phase}_{player}_syntax.txt 保存
        Engine->>Fallback: phase別フォールバック要求
        Fallback->>RNG: 必要なら候補から選択
        RNG-->>Fallback: fallback target
        Fallback-->>Engine: fallback action
        Engine->>Log: results.md に syntax error を記録
    else JSON構文OK
        Validator->>Validator: 厳密スキーマ検証
        alt 意味エラー
            Validator-->>Engine: semantic error
            Engine->>Log: raw/{seq}_{phase}_{player}_semantic.txt 保存
            Engine->>Fallback: phase別フォールバック要求
            Fallback->>RNG: 必要なら候補から選択
            RNG-->>Fallback: fallback target
            Fallback-->>Engine: fallback action
            Engine->>Log: results.md に semantic error を記録
        else 正常
            Validator-->>Engine: valid action
        end
    end
```

### 7.1 厳密JSON検証ルール

Phase 1では、応答全体が単一JSONオブジェクトでなければ不正とする。

不正扱い:

- Markdownコードフェンス
- JSON前後の説明文
- 定義外キー
- 必須キー欠落
- 空文字
- `null`
- 型不一致
- 存在しないプレイヤー名
- 自分自身を占い先・投票先にするなど、フェーズごとの禁止対象

### 7.2 フォールバックの保存先

生応答は以下に保存する。

```text
logs/games/game_XXXX/raw/{seq:02d}_{phase}_{player}_{error_type}.txt
```

例:

```text
logs/games/game_0001/raw/01_night_Codex_syntax.txt
logs/games/game_0001/raw/02_vote_Grok_semantic.txt
```

---

## 8. Phase 3 real-CLI 参考シーケンス

対象ユースケース: UC-02 / UC-06 / UC-07 / UC-08 / UC-11

Phase 3では、DryRunAgentの代わりにAgentInvokerが外部AI CLIを呼び出す。

```mermaid
sequenceDiagram
    autonumber
    participant Engine as GameEngine
    participant Prompt as PromptBuilder
    participant Invoker as AgentInvoker
    participant Temp as TemporaryDirectory
    participant CLI as External AI CLI
    participant Validator as JsonValidator
    participant Fallback as FallbackHandler
    participant Log as LogWriter

    Engine->>Prompt: プレイヤー用プロンプト生成
    Note over Prompt: 自分の役職、公開ログ、必要な秘密情報のみ含める<br/>game_state.json全体や他者の役職は含めない

    Prompt-->>Engine: prompt text
    Engine->>Temp: プレイヤーごとの一時ディレクトリ作成
    Engine->>Invoker: CLI呼び出し要求(prompt, temp_dir)

    Invoker->>CLI: subprocess.run(shell=False, cwd=temp_dir, prompt)
    Note over Invoker,CLI: リポジトリ直下では起動しない<br/>--yolo / --always-approve は使わない<br/>ファイル編集・シェル実行は許可しない

    alt 正常終了
        CLI-->>Invoker: stdout / stderr
        Invoker-->>Engine: raw response
        Engine->>Validator: 厳密JSON検証
        alt valid
            Validator-->>Engine: valid action
        else syntax/semantic error
            Validator-->>Engine: invalid
            Engine->>Log: raw/{seq}_{phase}_{player}_{error}.txt 保存
            Engine->>Fallback: フォールバック
            Fallback-->>Engine: fallback action
            Engine->>Log: results.md にエラー記録
        end
    else timeout
        Invoker-->>Engine: timeout error
        Engine->>Log: raw/{seq}_{phase}_{player}_timeout.txt 保存
        Engine->>Fallback: フォールバック
        Fallback-->>Engine: fallback action
        Engine->>Log: results.md に timeout 記録
    else CLI異常終了
        Invoker-->>Engine: cli error
        Engine->>Log: raw/{seq}_{phase}_{player}_cli.txt 保存
        Engine->>Fallback: フォールバック
        Fallback-->>Engine: fallback action
        Engine->>Log: results.md に cli error 記録
    end

    Engine->>Temp: 一時ディレクトリ削除
```

### 8.1 Phase 3の安全条件

- 外部AIはリポジトリ直下で起動しない。
- 外部AIはプレイヤーごとの一時ディレクトリで起動する。
- `game_state.json` や `private/` 情報は渡さない。
- 他プレイヤーの役職は渡さない。
- 渡すのはプロンプト本文のみとする。
- CLI出力は厳密JSON検証する。
- `--yolo` / `--always-approve` は使わない。
- AIプレイヤーにファイル編集や任意シェル実行を指示しない。

---

## 9. 保存ファイルの更新順

1試合ごとに、以下の順で保存する。

```text
1. logs/games/game_XXXX/game_state.json を初期化（phase=setup）
2. logs/games/game_XXXX/public_log.md を初期化
3. logs/games/game_XXXX/results.md を初期化
4. 役職割当後、game_state.json を更新（phase=night）
5. 夜フェーズ後、seer_result を game_state.json に保存（phase=speech）
6. 発言ラウンド中、public_log.md に発言を逐次追記（phase=vote に更新）
7. 投票ラウンド終了後、public_log.md に投票結果を一括追記
8. 処刑・勝敗判定後、game_state.json（phase=finished）/ public_log.md / results.md を保存
```

`phase` の許容値は `setup` → `night` → `speech` → `vote` → `finished` の5つとし、各処理の開始前に更新する（QandA Q37）。

**ルート直下への複製について（QandA Q30・Q31・Q33）**: Phase 1・Phase 3とも `SPEC.md` 14章の定義どおり、`logs/games/game_XXXX/` 配下にのみ保存する。ルート直下へのコピー、シンボリックリンク、ショートカットは作成しない。これによりQ30・Q31は前提ごと解消する。

---

## 10. 実装時の注意点

### 10.1 Q24〜Q29への対応方針

`QandA.md` の USECASE.mdレビューで指摘されたQ24〜Q29は、`USECASE.md` 自体を修正し、Codex CLIの再レビューでAPPROVEDとなったことで解消済みである（矢印方向のUML準拠化、UC-03/UC-11のPhaseタグ修正、UC-04の再現範囲の明記、UC-03詳細セクションの追加、乱数消費記述の整理）。

本書（SEQUENCE.md）は、修正後の `USECASE.md` の内容と整合する形で以下を扱う。

- Q24: 矢印方向はUSECASE.md側の表記の問題であり、Mermaid sequenceDiagramには直接影響しない。
- Q25: UC-03はPhase 1の複数試合逐次実行ループとして扱う（5章）。横断集計はUC-12 / Phase 4。
- Q26: UC-11はPhase 1/3横断とし、Phase 1はsyntax/semantic、Phase 3はtimeout/cliも対象（7章）。
- Q27: UC-04の完全再現はPhase 1 dry-runのみ。Phase 3はエンジン内乱数のみ再現（6.2章）。
- Q28: 本書5章でUC-03の詳細シーケンスを補足した。
- Q29: 本書6章で乱数消費順をSPEC 16.5相当に揃えた。

### 10.1.1 Q30〜Q40への対応方針

本書自体のレビューで指摘されたQ30〜Q40は、以下のとおり本書に反映済み。

- Q30・Q31・Q33: Phase 1・Phase 3ともルート直下の3ファイルを作成せず、試合ディレクトリ配下だけに保存する（9章参照）。これによりQ30・Q31は前提ごと解消。
- Q32: SPEC.mdバージョン表記の不整合はなし（解決済み・確認のみ）。
- Q34: dry-run発言JSONに`reason`を追加し、必須キー欠落によるフォールバック誤発火を防止した（4章参照）。
- Q35: `logs/games/game_XXXX/`の作成をループ内・試合ごとに移した（4章・5章参照）。
- Q36: `--dry-run`と`--use-real-agents`の同時指定はエラー終了（相互排他）とした（4章参照）。
- Q37: `game_state.json.phase`の許容値を`setup`→`night`→`speech`→`vote`→`finished`に確定した（4章・9章参照）。
- Q38: 書き込み失敗時は実行全体を非0終了とし、完了済み試合は変更せず、不完全ディレクトリは削除しない方針とした（5.1章参照）。
- Q39: Phase 3の`--seed`再現性は「同一シード・同一乱数呼び出し列であれば各選択結果は再現される」という限定的な保証とした（6.2章参照）。
- Q40: `--games`は1以上の整数であることを検証し、不正時は副作用前にエラー終了する方針とした（4章参照）。

### 10.2 Phase 1実装で優先すること

- `python scripts/run_game.py --games 1 --dry-run` が最後まで通ること。
- `python scripts/run_game.py --games 10 --dry-run --seed 1234` が毎回同じ結果になること。
- 外部AI CLIを一切呼ばないこと。
- JSON検証・フォールバックは、通常dry-runでは発火しないが、ユニットテストで検証できる構造にすること。

---

## 11. Phase 1 dry-run実装可否

本書の範囲では、Phase 1 dry-run実装に進める。

理由:

- ゲーム進行順が確定している。
- 乱数消費順が確定している（試合ごとのディレクトリ作成タイミングを含む）。
- dry-run応答の生成方針が確定している（発言JSONの`reason`欠落バグを含め修正済み）。
- 投票の同時性と公開タイミングが確定している。
- 保存ファイルとディレクトリ採番が確定している（ルート直下への複製は行わない）。
- JSONエラー・意味エラー時のフォールバック方針が確定している。
- `phase`値の遷移、モードフラグの相互排他、CLI引数検証、書き込み失敗時の扱いが確定している。

USECASE.md（Q24〜Q29）・SEQUENCE.md自体（Q30〜Q40）のレビュー指摘はいずれも解消済み。Phase 1 dry-run実装に進める状態である。

---

## 12. Phase 4 複数試合集計

```mermaid
sequenceDiagram
    actor Operator as 運用者
    participant Analyzer as analyze_results.py
    participant Games as logs/games
    participant Output as stdout / output file

    Operator->>Analyzer: --logs-root / --format / --output
    Analyzer->>Games: game_XXXX を番号順に列挙
    loop 各試合
        Analyzer->>Games: game_state.json 読込・検証
        alt finishedかつ妥当
            Analyzer->>Games: public_log.mdを補助読込
            Analyzer->>Analyzer: 陣営・プレイヤー・役職成績を加算
        else 未完了・破損・必須キー欠落
            Analyzer->>Analyzer: skippedとwarningを加算
        end
    end
    Analyzer->>Output: MarkdownまたはJSON
```

- `game_state.json`を正本とし、`raw/`は読まない。
- `public_log.md`は同票処刑と人狼処刑票を判定する補助入力であり、欠落しても試合を無効にしない。
- 1件の不正試合で全体処理を停止しない。
- logs-root不存在だけは非0終了する。
