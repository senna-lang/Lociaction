# lociaction

<p align="center">
  <a href="https://github.com/senna-lang/lociaction/actions/workflows/ci.yml"><img src="https://github.com/senna-lang/lociaction/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/lociaction/"><img src="https://img.shields.io/pypi/v/lociaction" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

<p align="center"><a href="README.md">English</a> · 日本語</p>

AI コーディングエージェントは、2 つの想起プリミティブ — `loci search` と `loci context` — に加え、両方を融合したセッション開始用の複合コマンド `loci recall` で、自分がやってきたことを思い出せます。エージェントは迷うことなく適切な呼び出しを選び、過去の意思決定・会話・正確なコード位置を 0.2 秒以内に復元します。

CLI コマンド `loci` は**エージェント自身が呼び出す**ことを想定しています — `loci search "..." --json` をプロンプト内から実行します。*(名前は記憶術 [Method of Loci＝記憶の宮殿](https://ja.wikipedia.org/wiki/%E5%A0%B4%E6%89%80%E6%B3%95) に由来します。内部では会話を「palace object」に蒸留します（[仕組み](#仕組み)を参照）。アーキテクチャは [arXiv:2603.13017](https://arxiv.org/abs/2603.13017) の会話記憶モデルをコーディングエージェント向けに拡張したものです。)*

> **対応 harness:** Claude Code、Codex CLI、Oh My Pi、OpenCode、Grok のセッションログを、同一の exchange・code touch・symbol・search・context・`show` 契約で扱います。蒸留はそれとは独立した選択で、`loci distill` はどの harness 由来の exchange であっても同じ設定済み client（`claude-cli`、`codex-cli`、`gemini-cli`、`grok-cli`、`opencode-cli`、`omp-cli`、ローカルの Ollama モデル、任意の OpenAI 互換エンドポイント）を使って蒸留します。

## ミニマルなインターフェース

想起のインターフェースは 2 つのプリミティブ + 1 つの複合コマンドで構成されます:

- **`loci search "クエリ"`** — 過去の会話をセマンティック検索
- **`loci context`** — 逆引き。コードシンボル（`--symbol "名前"`）または git ブランチ（`--branch "名前"`）から
  - tree-sitter のシンボル解決（Python / TypeScript / Go / Rust / Java / C# / Ruby）により、エージェントは編集前に実装意図を把握できる
  - `--branch "名前"` は特定の git ブランチで何をしたか・議論したかを想起（`loci search "クエリ" --branch "名前"` でも可）
- **`loci recall --file PATH --branch NAME`** — セッション開始ウォームアップ。`context` + `search` を recency 順に融合、`--file`/`--branch` はAND条件で組み合わせ可能

これは意図的な設計です。ここでの利用者はエージェント自身であり、50 個のツールを渡されたエージェントは迷い、選び間違え、どれを呼ぶか決めるだけでトークンを消費します。表面がこれだけ小さく — かつ MCP のツール定義がコンテキストウィンドウに常駐しない — ので、エージェントは毎回・最初から正しい呼び出しに手を伸ばします。*(会話原文が必要なときは `loci show "<exchange-id>"` で検索結果の原文を取り出せます。)*

シンボルに触れることは、それについて決めたことを想起すること — `loci context` は正確なコード位置・シグネチャと、その背後にある会話を逆引きします。

## 仕組み

1. **Index** — エージェントのセッションログを exchange（ユーザー発話 + エージェント応答のペア）に分割し、FTS5 でキーワード検索可能にする
2. **Distill** — 設定済みの蒸留 client（既定は `claude --print` + `claude-haiku-4-5`。他5つの CLI backend やローカルモデルは[設定](#設定)を参照）が各 exchange を palace object に要約: `exchange_core`（何をしたか）、`specific_context`（具体的な詳細）、`room_assignments`（トピックタグ）。tree-sitter で触れたファイルをシンボルレベル（関数・クラス・メソッド + ファイル + 行 + シグネチャ）に解決
3. **Search** — 会話原文の BM25 と蒸留済み埋め込みの HNSW を RRF で融合するクロスレイヤー検索

会話原文は埋め込まず、蒸留で濃縮されたテキストのみを `multilingual-e5-small`（384次元）で埋め込むことで、セマンティック検索の精度と埋め込みコストを両立しています。埋め込みモデルは **Unix ソケットサーバー**で常駐し、初回以降の検索は **0.2 秒以内**で返ります。

## インストール

```bash
pipx install lociaction
```

Python 3.11 以上が必要です。

## クイックスタート

```bash
# プロジェクトルートで初期化。共有エージェント指示を AGENTS.md に追加します。
loci init
```

`loci init` は project-local DB を作成し、共通の `AGENTS.md` 指示を追加します。Claude Code フックは `--no-hooks` を指定しない限り登録します。他の対応 harness（Codex、Grok、Oh My Pi、OpenCode）も全て native lifecycle hook に完全対応しており、`loci hook install --harness <name>` で明示的に登録します。

`loci init` を実行すると、過去のセッションログが検出された場合に以下の質問が表示されます:

> [!IMPORTANT]
> 途中からこのツールを導入する場合、すでに大量の exchange が蓄積されています。全件蒸留すると、選択した蒸留 client（既定は Claude Haiku。他の選択肢は下記ステップ4参照）に対して実際にトークンを消費するため、まずは `Skip all` か `Distill last 50` で始めることを推奨します。

1. **Min chars threshold** — インデックス時に適用される最小文字数フィルタ（デフォルト: 50文字）。短い exchange はそもそもインデックスされず、その結果として蒸留の母数も減ります。値を大きくすると短い会話が除外され、小さくするとほぼ全ての会話が対象になりトークン消費が増えます。（蒸留には別途 `min_chars=100` のフィルタがあります — [設定](#設定)を参照。）
2. **既存 exchange の扱い** — 過去のセッションをどこまで蒸留するか選択:
   - Skip all（過去のセッション蒸留なし）
   - Distill last 50（直近の履歴のみ）
   - Distill all（全件、トークン消費あり）
   - Custom（件数を指定）
3. **蒸留を今すぐ実行するか** — `1`/`2`/`y`/`n`/`yes`/`no` を受理。No を選ぶと次回セッション開始時に自動実行されます。

過去のセッション履歴の有無にかかわらず、`loci init` は一度だけ次も尋ねます:

4. **蒸留 client の選択** — [`qwen2.5-7b-memory-distiller`](https://huggingface.co/sennaLLMLearner/qwen2.5-7b-memory-distiller)（この蒸留タスク専用にファインチューンした Qwen2.5-7B。SFT + ORPO on WildChat-1M）がまだ pull されていなければ、`loci init` はまず `ollama pull` をオファーします（約4.7GB、[Ollama](https://ollama.com) が必要）。続けて、このマシンで実際に *Ready* と検出された蒸留 client — `claude-cli`、`codex-cli`、`gemini-cli`、`grok-cli`、`opencode-cli`、`omp-cli`、そして pull 済みなら `ollama-ft` — を一覧表示し、選択を求めます（`claude-cli` があれば既定で推奨されます）。実際に `PATH` に存在する CLI だけが表示され、これは今作業している harness とは無関係です（[設定](#設定)の補足を参照）。`--no-local-distiller` で Ollama pull のオファーをスキップ、`--distill-client <id>` で非対話に選択できます（その client が Ready でなければエラー終了 — 別 client への自動フォールバックはしません）。Ready な client が1つもなければ蒸留は未設定のまま残り、後で `loci distill --setup` を実行できます。

各プロンプトで無効な入力をした場合、サイレントにデフォルトへ倒れず再入力を求めます。

## エージェント向けインストラクション

`loci init` は全 harness 共通の正本である **`AGENTS.md`** に、マーカー付きセクション（`<!-- BEGIN LOCIACTION -->...<!-- END LOCIACTION -->`）を挿入します。`loci prime` は native lifecycle があるセッションへ詳細なコマンド利用法を注入します。

## CLI コマンド

| コマンド | 説明 |
|---------|------|
| `loci init [--distill-client ID]` | `.lociaction/` を初期化し、共通 `AGENTS.md` 指示を追加、Claude Code フックを登録（`--no-hooks` で省略可、`--no-local-distiller` で Ollama pull オファーを省略、`--distill-client` で蒸留 client を非対話に指定） |
| `loci index [--harness all\|claude\|codex\|opencode\|omp-pi\|grok]` | 新しいセッションログをインデックス（既定は検出した全 harness） |
| `loci distill [--limit N] [--setup]` | 設定済み client で未蒸留の exchange を蒸留。`--setup` は discover/選択をやり直して config に保存 |
| `loci gc` | `memory.db` を `.bak` に安全にスナップショットし、孤立した palace/vector/session レコードだけを削除。現行 backup と直近3世代を残して `VACUUM` |
| `loci search "クエリ" --json` | セマンティック検索（エージェント向け）。`--branch NAME` で git ブランチ絞り込み |
| `loci context --symbol "名前" --json` | コードシンボル → 過去の会話（軽量。`--full` で会話原文も含める） |
| `loci context --branch "名前" --json` | git ブランチ → 過去の会話（未蒸留の exchange も含む） |
| `loci recall --file PATH --branch NAME --json` | セッション開始ウォームアップ。context+search を融合し recency 順。`--file`/`--branch` は AND 可能 |
| `loci show "<exchange-id>" --json` | primary ID から会話原文を取得 |
| `loci status` | インデックス状態を表示 |
| `loci prime` | コマンドの使い方をセッションコンテキストに注入 |
| `loci server start/stop/status` | 埋め込みサーバー管理 |
| `loci hook install --harness NAME` | 対応する5 harnessいずれかの native lifecycle hook を登録 |
| `loci hook uninstall --harness NAME` | native lociaction lifecycle hook を削除 |

## Harness lifecycle

| Harness | transcript | native lifecycle |
|---------|------------|-------------------|
| Claude Code | project JSONL | `~/.claude/settings.json` |
| Codex CLI | recorded cwd で絞る rollout JSONL | `~/.codex/hooks.json` |
| Grok | project streaming JSONL | `~/.grok/hooks/lociaction.json` |
| Oh My Pi | project JSONL | `~/.omp/agent/extensions/lociaction.ts` |
| OpenCode | local session SQLite | `~/.config/opencode/plugins/lociaction.ts` |

対応する5 harnessは全て native lifecycle に完全対応しており、fallback/手動指示の経路は存在しません。turn end は `loci index` に、session start は `loci server start` + `loci distill` + `loci prime` に写像されます。compact の扱いは harness ごとに少し異なります: Claude Code と Codex CLI は compact を同じ session-start の3コマンドに畳み込みます（matcher に `compact` を含む）。Grok と OpenCode は compact 時に `loci prime` のみ実行します。Oh My Pi には compact 相当のイベントが無く、何もフックしません。`loci hook install/uninstall --harness NAME` はこれらを管理し、他の harness の設定には一切触れません。

## 検索出力

```json
[
  {
    "exchange_core": "pool_size=5 でコネクションプールを追加した",
    "specific_context": "pool_size=5, max_overflow=10",
    "rooms": [
      { "room_type": "concept", "room_key": "db-pool", "room_label": "DB コネクションプーリング" }
    ],
    "symbols": [
      { "name": "create_pool", "file": "src/db.py", "line": 42, "signature": "def create_pool(...)" }
    ],
    "verbatim_ref": "~/.claude/projects/.../session.jsonl:ply=42",
    "git_branch": "feature/db-pool"
  }
]
```

## 設定

`.lociaction/config.toml`（`loci init` で生成）:

```toml
[distill]
client = "claude-cli"                  # 蒸留 backend — id 一覧は下記参照
model = "claude-haiku-4-5-20251001"    # 蒸留に使うモデル（省略時は client ごとの既定値）
batch_limit = 20                       # 1回あたりの蒸留上限
min_chars = 100                        # この文字数未満の exchange は蒸留をスキップ

[index]
min_chars = 50                         # この文字数未満の exchange はインデックスをスキップ
```

`min_chars` は2か所あります。`[index] min_chars` はそもそもインデックス対象にするかを制御し、`[distill] min_chars` はインデックス済みの短い exchange について蒸留（LLM コスト）をさらにスキップします。

`client` は今作業している harness とは独立しています — `loci distill` は Claude Code / Codex / Grok / OpenCode / Oh My Pi のどれ由来の exchange でも、設定済みの client 1つで蒸留します（[Harness lifecycle](#harness-lifecycle)参照）。有効な id: `claude-cli`、`codex-cli`、`gemini-cli`、`grok-cli`、`opencode-cli`、`omp-cli`、`ollama-ft`、`openai-compat`。旧来の `provider = "claude" | "openai"` + `base_url` 形式も後方互換で読み込みますが、`loci init`/`loci distill --setup` が書き込むのは `client` であり、手で編集する場合もこちらを推奨します。

### ローカル LLM で蒸留する

蒸留は exchange ごとの小さな構造化抽出タスクなので、ローカルモデルでも十分なことが多いです。OpenAI 互換のエンドポイント（Ollama、LM Studio、llama.cpp-server、vLLM）なら `client = "openai-compat"` に `model`/`base_url` を指定するだけで動きます — 新規依存なし・API キー不要（`Authorization` ヘッダーは送らないため、ローカル専用です）:

```toml
[distill]
client = "openai-compat"
model = "qwen2.5:7b"
base_url = "http://localhost:11434/v1"   # Ollama
# base_url = "http://localhost:1234/v1"  # LM Studio
```

`openai-compat` は `model`/`base_url` の両方が必須です（欠けると解決に失敗します）。Ollama の既定ポートで同梱のファインチューン済みモデルを使うなら、代わりに `client = "ollama-ft"` を使ってください — モデルとエンドポイントを自動で知っています（[`loci init`](#クイックスタート)参照）。

`loci init` は [`qwen2.5-7b-memory-distiller`](https://huggingface.co/sennaLLMLearner/qwen2.5-7b-memory-distiller)（このタスク専用にファインチューンしたモデル。上記のプロンプト参照）でこのセットアップを自動的にオファーします — 承諾すれば手動設定は不要です。

### 他のコーディングエージェント CLI で蒸留する

[Codex CLI](https://developers.openai.com/codex/cli)、[Gemini CLI](https://github.com/google-gemini/gemini-cli)、[Grok CLI](https://x.ai)、[OpenCode](https://opencode.ai)、[Oh My Pi](https://github.com/can1357/oh-my-pi) のいずれかを既にインストール・認証済みなら、`claude --print` の代わりに蒸留を実行できます — client を選ぶだけで追加設定は不要です:

```toml
[distill]
client = "codex-cli"     # または "gemini-cli", "grok-cli", "opencode-cli", "omp-cli"
# model = "gpt-5-codex"  # 任意の上書き。省略時は各 CLI 自身の既定モデルを使う
```

`codex exec --output-schema` と `grok -p --json-schema` は palace object のスキーマに直接制約した応答を返します（grok は `structuredOutput` を1段 unwrap、codex はラップなし）。`gemini --prompt --output-format json`、`opencode run --format json`、`omp -p --mode json` にはスキーマ制約モードがないため、自由テキスト/イベントストリームの中から palace object を `claude --print` の `result` フィールドと同じ方法でパースします。`loci distill --setup` は5つとも自動検出し（`claude-cli` 同様 PATH 存在のみ確認）、他の Ready な client と並んで一覧表示されます。

## Acknowledgments

Palace object モデル、room ベースのトピックグルーピング、BM25+HNSW 融合検索は以下の論文に基づいています:

> *Structured Distillation for Personalized Agent Memory*
> (arXiv:2603.13017)


## ライセンス

MIT
