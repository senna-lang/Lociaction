# Changelog

## [Unreleased]

## [0.7.1] - 2026-09-22

### Fixed
- Native lifecycle hooks are now project-scoped. Although supported harnesses
  register hooks in their user-level configuration where required, every hook
  resolves the active Git project (or uses the cwd outside Git) and skips
  `loci index`, `loci server start`, `loci distill`, and `loci prime` unless
  that project has been initialized with `loci init`. Reinstalling an existing
  Claude, Codex, Grok, Oh My Pi, or OpenCode hook migrates its generated
  commands to the guarded form.

## [0.7.0] - 2026-09-21

### Added
- Harness initialization parity: `loci init` indexes existing sessions from
  every detected harness (Claude, Codex, Grok, Oh My Pi, OpenCode) under one
  configured threshold and one history-distillation decision, instead of
  only Claude history before the min-chars/skip-count prompts. Non-Claude
  harnesses now get explicit `loci hook install --harness <name>` guidance
  when detected, instead of staying silent.
- Distill client selection derives model choices from session-recorded
  model IDs for the detected project harness instead of a hard-coded or
  live-provider catalog, plus distillation progress reporting.
- `LOCI_LLAMACPP_MAX_CONCURRENT` (default 1): a machine-wide,
  cross-process counting semaphore so multiple projects distilling with
  `llamacpp-ft` concurrently don't each start an independent
  full-GPU-offload `llama-server` and contend for GPU/unified memory.
- Hermetic installed-wheel release sandbox (`make e2e`): builds the
  current source into a wheel, installs it into a fresh offline venv, and
  drives the installed `loci` executable through real onboarding,
  deferred-distillation, and non-Claude hook-install flows. Wired into
  `publish.yml` as a gate before every release-tag publish.

### Changed
- `llamacpp-ft` always appears in `loci distill --setup` / `loci init`
  (binary missing is setupable, not hidden). Selecting it finds
  `llama-server` including `~/llama.cpp/build/bin`, runs
  `brew install llama.cpp` if needed, and `ollama pull`s the FT + draft
  models. Apple Silicon defaults to `-ngl 99`.
- Codex project-scope filtering is unified: the same predicate now backs
  both model-catalog discovery and `loci index --harness codex`, closing a
  cross-project model-history leak.
- Selecting a remote CLI distill client (`claude-cli`/`codex-cli`/
  `gemini-cli`/`grok-cli`/`opencode-cli`/`omp-cli`) without an explicit
  `LOCIACTION_REMOTE_DISTILL_CLIENTS` grant now warns immediately at
  selection time, instead of only surfacing later as an unrelated,
  confusing "distill unconfigured" warning.

### Fixed
- `loci distill` no longer starts `llama-server` (a multi-GB model load)
  when there are 0 exchanges to distill. `distiller.has_pending_work`
  runs the same skip-marking + pending check as `distill_all` before
  binding the runtime backend.
- `loci init`'s history skip-count/priority selection ("Skip last N" /
  "Custom" + "Longest"/"Recent") now excludes exchanges that
  `distill_all` would unconditionally re-skip anyway (single-exchange
  conversations, or shorter than `distill.min_chars`) *before* applying
  the user's chosen count and priority. Previously the selection sorted
  purely by character length with no notion of that eligibility rule, so
  a user who picked "custom N" could see fewer than N actually distilled
  once `loci distill` ran and silently re-skipped an ineligible
  "kept-pending" exchange. `init` now also reports how many indexed
  exchanges are permanently ineligible, before asking how to handle the
  rest.

## [0.6.0] - 2026-09-15

### Added
- `llamacpp-ft` distill client: ephemeral `llama-server --model-draft`
  for classic speculative decoding on the bundled GGUF fine-tune.
  Ollama's `DRAFT` Modelfile path (the 0.5.0 attempt, reverted in 0.5.1)
  cannot accelerate this model — it is safetensors/MTP-only. The new
  backend resolves Ollama GGUF blobs from local manifests, starts
  `llama-server` on a loopback port for one `loci distill` batch, and
  stops it afterwards. Requires `llama-server` on `PATH` or
  `LOCI_LLAMACPP_SERVER`. Draft model defaults to `qwen2.5:0.5b`; set
  `LOCI_LLAMACPP_DRAFT_MODEL=` to opt out. GPU offload is not forced
  (`LOCI_LLAMACPP_GPU_LAYERS` / `LOCI_LLAMACPP_DRAFT_GPU_LAYERS` to
  override). Selection/setup stays TTY-gated; a configured client may
  run from a hook without downloading. `loci init` / `loci distill --setup`
  recommend `llamacpp-ft` when it is Ready.

### Removed
- `ollama-ft` distill client. Ollama remains the GGUF blob source
  (`ollama pull`); talking to Ollama's HTTP API is `openai-compat`.

## [0.5.1] - 2026-09-15

### Fixed
- Reverted the automatic speculative-decoding drafter for `ollama-ft`
  added in 0.5.0 (issue #1). Ollama's `DRAFT` Modelfile instruction
  requires a local filesystem path to draft-model weights, not a
  registry tag, so `ollama create loci-distiller` always failed with
  `stat ...: no such file or directory`. Worse, `DRAFT`/MTP speculative
  decoding only works when the `FROM` base model itself contains MTP
  (multi-token-prediction) layers baked into its weights; the community
  fine-tune this project bundles (`qwen2.5-7b-memory-distiller`) is a
  standard fine-tune with none, so even a corrected Modelfile path fails
  at inference (`context type MTP requested but model doesn't contain
  MTP layers`). The pairing cannot work against this base model as
  designed, so it is removed rather than patched. `ollama-ft` behaves
  exactly as it did before 0.5.0: it pulls and uses
  `hf.co/sennaLLMLearner/qwen2.5-7b-memory-distiller:Q4_K_M` directly,
  with no drafter. No user action is required — the 0.5.0 setup/upgrade
  path always failed cleanly (falling back to the raw model, per its own
  error handling) and never left a broken `loci-distiller` model behind.

## [0.5.0] - 2026-09-14

### Added
- `ollama-ft` paired the fine-tuned distillation model with a
  speculative-decoding drafter (`qwen2.5:0.5b`), combined into a local
  `loci-distiller` Ollama model. **Reverted in 0.5.1** — see its entry
  for why this never worked in practice.

## [0.4.0] - 2026-09-14

### Added
- `loci eval gate` (issue #37) is a CI regression gate for symbol-recall.
  It builds a tiny synthetic git+`code_edges` fixture (no network, no
  embeddings, no dogfood corpus) and fails if MRR@10 drops more than an
  absolute 0.01 against committed `src/lociaction/eval/baseline.json`.
  Keyword-recall (BM25/HNSW/RRF) remains out of scope.

- `loci status` now surfaces the most recent distill per-row failure
  (`exchange_id`, message, timestamp) from `meta` when one has been
  recorded; the field/section is omitted when nothing failed.

- `loci recall` (issue #33, redesigned) is a resume-style session browser,
  not an exchange-level merge. `loci recall` (bare) lists sessions newest
  first; `loci recall "query"` ranks sessions by relevance (exchange-level
  BM25(V)+HNSW(D) RRF scores aggregated to `session_id` by max, so a long
  session can't out-rank a strong single hit on exchange count alone);
  `loci recall --session ID` returns that session's digest — `exchange_core`
  (the distilled one-line decision) per exchange in ply order, not full
  transcripts; `--full` adds `specific_context`/`user_content`/`agent_content`
  per line. `--file`/`--branch` are independent AND filters on either list
  mode. Keyword-mode recency decay now defaults OFF (`--recency-half-life 0`)
  so today's session can't bury older relevant ones by recency alone —
  the flat 0.10 semantic confidence that caused this in the old merge is
  gone along with the merge itself.

- `loci gc` (issue #30) snapshots the database, removes only orphaned
  palace/vector and exchange/session records, retains bounded `.bak` archives,
  and compacts the database with `VACUUM`.

- `loci hook install`/`uninstall --harness omp-pi|opencode|grok` now write real
  native hooks (issue #40): `OmpPiHooks`/`OpenCodeHooks` generate a marker-owned
  `~/.omp/agent/extensions/lociaction.ts` / `~/.config/opencode/plugins/lociaction.ts`
  plugin file (`DedicatedFileWriter`), and `GrokHooks` merges into a dedicated
  `~/.grok/hooks/lociaction.json` (`MergedJsonHookWriter`, shared with the new
  `CodexHooks`). All three previously always failed via `FallbackHooks`, which
  remains the safety net for unrecognized harnesses.

### Changed
- Database schema v14 removes unused `vec_exchanges`, obsolete
  `code_touches.symbol_name`/`resolved_by`, and duplicate `symbols` storage.
  Existing live legacy symbol relations migrate to `code_symbols` plus
  `code_edges` before the old table is dropped.

- Lifecycle event → loci command mapping (`Stop`→`index`, `SessionStart`→
  `server start`/`distill`/`prime`, compact→`prime`) is now a single source of
  truth: `lociaction.adapters.harness.lifecycle.lifecycle_commands(harness,
  batch_limit)`. `ClaudeHooks`/`CodexHooks`/`GrokHooks`/`OmpPiHooks`/
  `OpenCodeHooks` all derive their commands from it instead of re-deriving
  the mapping per harness (`lociaction.hooks.install_hooks`/`uninstall_hooks`
  keep their Claude-specific JSON-merge/idempotency logic, only the command
  strings themselves are now sourced from the shared helper). One observable
  side effect: Claude's `Stop` hook now runs `loci index --harness claude`
  instead of the previous bare `loci index` (which implicitly swept every
  detected harness on each Claude turn), matching the scoping Codex already had.
- `DedicatedFileWriter` uninstall only ever deletes files carrying its own
  `LOCIACTION_HOOK_MARKER`; files without the marker (other tools' extensions/
  plugins sharing the same auto-discovered directory) are left untouched on
  both install (no clobber) and uninstall (no delete).

### Fixed
- Distillation and indexing now reject session-log paths that resolve
  outside the project root, so a crafted tool-use path cannot make
  `loci distill` read arbitrary local files.
- `loci init` appends `.lociaction/` to the project `.gitignore` when
  missing, so the local memory database is not staged by a bulk commit.
- Sensitive-file redaction now treats any tool-use `file_path` /
  `notebook_path` as a touched path and canonicalizes relative paths
  before matching `.lociaction/ignore`.
- `.lociaction/ignore` drops overlong or wildcard-heavy rules instead of
  compiling them into unbounded backtracking regexes.
- `SymbolResolver` returns no symbols for a pathologically deep AST
  instead of aborting ingest/distill with `RecursionError`.
- Unified-diff hunk coordinates that are too large to convert safely are
  skipped instead of crashing `loci index`.
- Session-log JSONL loaders bound per-line bytes, aggregate bytes, and
  retained entries so an adversarial log cannot exhaust memory.
- `distill.base_url` must be `http`/`https` with a host and no userinfo.
- Plain-text `show`/`dump`/`search`/`context`/`recall` output strips
  terminal control sequences from stored session content.

- `loci search`'s KNN→filter ordering and branch matching (issue #18):
  - `search_hnsw_palace` cut the sqlite-vec KNN candidate pool to exactly
    `limit` *before* applying the `min_exchanges`/`branch` filters, so a
    branch- or activity-filtered query could silently drop to zero results
    even when relevant matches existed just outside the initial top-K. The
    candidate pool is now widened adaptively: it starts at `limit * 5`, and
    if filtering leaves fewer than `limit` results while unexplored candidates
    remain in `vec_palace`, the pool doubles and the query retries (bounded by
    a `2000`-candidate hard cap so worst-case ANN cost stays finite even under
    a highly selective filter). The final result count is still enforced with
    an outer `LIMIT`.
  - `search_bm25`/`search_hnsw_palace`'s `branch` filter interpolated the
    user-supplied branch string into a `LIKE '%...%'` pattern unescaped, so
    literal `%`/`_` in the query were interpreted as SQL wildcards (e.g.
    `main` incorrectly matching `maintenance`/`feat/main-x`). Wildcard
    characters are now escaped (new `lociaction.utils.escape_like`) and the
    clause carries an explicit `ESCAPE '\\'`; substring matching on
    non-wildcard input is unchanged.
- Embedding server lifecycle races (issue #16): `loci server start` now serializes
  the check→spawn→ready-wait sequence behind a process-wide `server.lock`
  (`fcntl.flock`), eliminating double-spawn/orphaning under concurrent sessions.
  `run_server` pings an existing socket before binding and refuses to clobber a
  live server. `loci server status` is now strictly read-only and never deletes
  a busy-but-unresponsive socket. `Embedder` serializes `model.encode` calls
  across threads (`SentenceTransformer` inference is not thread-safe). The
  embedder server now removes its PID file on idle-timeout/stop, not just the
  socket.

### Security
- `.lociaction/ignore` matching replaced regex-backtracking wildcard
  evaluation with a linear-time DP matcher; the total normalized path
  length is capped and fails **closed** (treated as excluded) rather than
  open when exceeded. The `?` wildcard, previously compiled but silently
  never matched, now matches a single character as documented.
  `load_ignore()` opens the ignore file through a no-follow, non-blocking
  directory-relative descriptor instead of check-then-open, closing a
  symlink/FIFO TOCTOU. `IgnoreMatcher.matches()`/`matches_any()` memoize
  results per normalized path with a bounded cache.
- Harness session-log discovery (`resolve_claude_projects_path`,
  `resolve_codex_sessions_path`, `resolve_omp_pi_sessions_path`,
  `resolve_grok_sessions_path`) now walks candidate directories through a
  helper that bounds total filesystem entries visited, not just matches
  consumed, so a decoy-file-flooded harness directory can't make
  discovery unbounded. `session_file_matches_project_root()` opens the
  candidate session file through a no-follow, non-blocking
  directory-relative descriptor (closing a stat-then-open TOCTOU and a
  FIFO-blocking risk) and tolerates a `RecursionError`/`MemoryError` from
  a maliciously deep-nested metadata line and a symlink-loop
  `RuntimeError` from resolving a crafted `cwd`. `resolve_opencode_db_path()`
  now rejects a symlinked or special-file (FIFO, etc.) database path
  before it ever reaches SQLite.
- `load_config()` enforces a file-size cap before parsing
  `.lociaction/config.toml` and now catches `MemoryError`/`RecursionError`
  alongside `TOMLDecodeError`, falling back to defaults like every other
  malformed-config case instead of crashing. A tracked
  `distill.batch_limit` above a fixed ceiling is rejected, so a cloned
  repository's config can no longer expand automatic distillation to all
  pending exchanges.
- `write_client_config()` (the `loci init`/`loci distill --setup` config
  writer) applies the same size and regular-file guards to the existing
  config it preserves before rewriting `[distill]`/`[index]`.
- Grok session parsing caps the number of distinct edit tool-call IDs
  accepted per exchange and discards the whole exchange's touches, fail
  closed, past the cap, bounding the ingestion work a single hostile
  exchange can cause.
- An unknown `--distill-client` value is sanitized before being echoed
  to the terminal, matching every other untrusted-text error path in
  `loci init`.

## [0.3.0] - 2026-06-12

### Added

- Branch linking: exchanges are linked to their git branch at index time.
- `loci search "query" --branch NAME` — branch-filtered semantic search.
- `loci context --branch NAME` — reverse lookup from a git branch to past conversations (includes undistilled exchanges).
- `loci context --full` flag; the default output is now lighter.
- `loci hook uninstall` — remove lociaction hooks from `settings.json`.
- SQLite hardening: WAL mode, `busy_timeout`, and a `user_version`-based migration framework.
- Distillation transactions with `distill_status` and version tracking, plus new indexes.

### Changed

- `loci prime` output rewritten around agent-action triggers with concrete examples.
- Distillation uses a flock-based lock; embeddings are serialized with `tobytes`.
- Hook registration writes `settings.json` atomically.
- Indexing is incremental and reports config errors explicitly.

### Fixed

- Silent data loss in the distillation pipeline; code reverse-lookup works again.
- Embedding server can no longer double-start; socket protocol hardened and connection leaks fixed.
- Ply coordinate drift and WAL sidecar file permissions.
- `loci prime` exits silently when `.lociaction/` is absent; resolving `.lociaction/` from a parent directory now notifies on stderr.

## [0.2.0] - 2026-04-21

### Added

- `loci init --no-hooks` flag to skip automatic Claude Code hook registration.
- `EmbedderSetupError` exception for environment-level embedder failures (distinguishes them from per-row errors).
- SVG banner at the top of the README (`assets/banner.svg`, generated via Freeze).
- `scripts/generate-banner.sh` to regenerate the banner from the live CLI output.

### Changed

- `loci init` now registers Claude Code hooks automatically at the end of setup — previously required a separate `loci hook install` step. Use `--no-hooks` to opt out.
- Interactive prompts re-prompt on invalid input instead of silently falling back to a default. The "run distillation now?" prompt now accepts `y`/`n`/`yes`/`no` in addition to `1`/`2`.
- Custom exchange counts are range-validated (`1..total`) and custom `min_chars` requires `>= 0`.
- Startup banner uses the pagga half-block font with a blue vertical gradient.

### Fixed

- `loci init` cleans up `.lociaction/` automatically if the execution phase fails or is interrupted (`KeyboardInterrupt`), so re-running is safe.
- A single corrupt `.jsonl` no longer aborts the whole indexing loop — it logs a warning and continues.
- `git_root()` catches `FileNotFoundError` when the `git` binary is missing.
- `parse_exchanges` returns `[]` for missing files instead of raising.
- Distillation failures from `sentence_transformers` import issues (e.g. numpy/pyarrow binary mismatch) now print a single friendly message with remediation hints instead of a full traceback followed by per-row error spam.

## [0.1.0] - 2026-03-31

### Added

- `loci init` — initialize `.lociaction/` in project root
- `loci index` — parse `.jsonl` session logs, split into exchanges, embed with multilingual-e5-small
- `loci distill` — distill exchanges via `claude --print` into palace objects (exchange_core, specific_context, room_assignments)
- `loci search` — cross-layer RRF fusion search (BM25 verbatim + HNSW distilled)
- `loci context` — reverse lookup: code symbol → past conversations
- `loci show` — fetch verbatim exchange by ref
- `loci status` — show index state
- `loci server start/stop/status` — Unix socket embedding server for <0.2s search
- `loci hook install` — register Claude Code SessionStart/Stop hooks
- `config.toml` support for distill model and batch limit
- tree-sitter symbol resolution (Python, TypeScript, Go)
- Bilingual support (Japanese + English) via multilingual-e5-small
