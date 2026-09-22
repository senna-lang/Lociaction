---
description: Supported session-log harnesses, transcript sources, and native lifecycle hooks.
---

# Harnesses

Lociaction indexes session logs from five harnesses into the same exchange, code-touch, symbol, search, context, and `show` contracts. Distillation is independent of the harness — see `loci docs show distillation`.

## Sources and native lifecycle

| Harness | Transcript source | Native lifecycle |
| --- | --- | --- |
| Claude Code | Project JSONL | `~/.claude/settings.json` |
| Codex CLI | Global rollout JSONL filtered by recorded cwd | `~/.codex/hooks.json` |
| Grok | Project streaming JSONL | `~/.grok/hooks/lociaction.json` |
| Oh My Pi | Project JSONL | `~/.omp/agent/extensions/lociaction.ts` |
| OpenCode | Local session SQLite | `~/.config/opencode/plugins/lociaction.ts` |

`loci init` indexes existing sessions from every detected harness using one
threshold and one history-distillation decision. It installs only Claude Code
hooks unless `--no-hooks` is passed. Register any other detected harness
explicitly:

```bash
loci hook install --harness claude
loci hook install --harness codex
loci hook install --harness grok
loci hook install --harness omp-pi
loci hook install --harness opencode
loci hook uninstall --harness NAME
```

Install/uninstall never touches another harness's settings. Native hook configuration
is user-level where the harness requires it, but each command first resolves the
current Git project (or uses the cwd outside Git) and runs only when that project's
root contains `.lociaction/`. Therefore an installed hook does nothing in projects
where `loci init` has not been run.

## What the hooks run

Turn end maps to `loci index`. Session start maps to `loci server start` + `loci distill` + `loci prime`.

Compact handling differs:

- Claude Code and Codex CLI fold compact into the same session-start trio.
- Grok and OpenCode run only `loci prime` on compact.
- Oh My Pi has no compact-equivalent event.

`loci prime` prints agent instructions only in an initialized project. Hooks also
skip `loci index`, `loci server start`, and `loci distill` before their processes
start when `.lociaction/` is absent.

## Indexing

```bash
loci index
loci index --harness claude
loci index --harness opencode --path /path/to/opencode.db
```

Default `--harness all` indexes every detected harness. If a sessions directory or OpenCode DB cannot be found, pass `--path`.
