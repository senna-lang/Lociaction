---
description: Diagnose initialization, indexing, hook, embedding-server, and distillation failures.
---

# Troubleshooting

Run `loci docs list` for the full topic list. Recovery commands below stay authoritative; this page adds background.

## Not initialized

```text
Not initialized. Run `loci init` first.
```

There is no `.lociaction/memory.db` in this project (or a parent). Run `loci init` from the project root. For scripts and agents, see `loci docs show getting-started` (non-interactive flags).

`loci docs` itself does not need initialization.

## Distill client not configured or not ready

```text
Distill client is not configured. Run `loci distill --setup`.
Configured distill client '…' is not ready (…). Not switching automatically.
```

Lociaction will not silently pick another client. Fix PATH / auth / Ollama, then:

```bash
loci status --check
loci distill --setup
```

See `loci docs show distillation`.

## Index found no sessions

```text
No detected harness sessions.
No session files found.
OpenCode session DB not found. Use --path to specify.
… sessions dir not found. Use --path to specify.
```

Confirm the harness is one of: `claude`, `codex`, `opencode`, `omp-pi`, `grok`. Pass `--path` when the default location is wrong. Codex rollouts outside this project's cwd are ignored. See `loci docs show harnesses`.

## Hooks

```bash
loci hook install --harness NAME
loci hook uninstall --harness NAME
```

If settings fail to load, the command prints the error and exits 1 without writing a partial config. Install never edits another harness. `loci prime` is silent when `.lociaction/` is missing — that is intentional.

## Embedding server

Search uses a Unix-socket embedding server.

```bash
loci server status
loci server start
loci server stop
```

`start` requires an initialized project. If a socket exists but does not respond, stop and start again. The first search after a cold start loads the model and is slower; later searches should stay under ~0.2s.

Drift warning:

```text
[warn] <key> changed (<recorded> -> <current>). Re-index recommended.
```

That is a stderr warning. Re-run `loci index` after upgrading lociaction if embeddings or schema drift.

## Distill failures

`loci status` (and `loci status --json`) expose `last_distill_error` when a run failed. Typical causes: client not ready, lock held by another distill, or a model returning unparseable output. Retry `loci distill` after fixing readiness. Do not switch to a paid client just to unblock a test.

## Inspecting stored data

```bash
loci status --json
loci show "<exchange-id>" --json
```

Treat `show` / `dump` output as private. See `loci docs show privacy`.
