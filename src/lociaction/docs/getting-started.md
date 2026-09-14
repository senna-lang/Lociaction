---
description: Install lociaction, run `loci init`, and complete interactive or non-interactive setup.
---

# Getting started

Lociaction is a local-first memory layer for AI coding agents. The `loci` CLI indexes agent-session logs, records code touches, and recalls prior decisions.

These documents ship inside the installed package. Prefer `loci docs show <name>` over web pages — the text matches this exact version.

## Install

Requires Python 3.11+.

```bash
pipx install lociaction
```

Confirm the binary:

```bash
loci --version
loci docs list
```

`loci docs` does not need a project, network, an embedding server, or a distill client.

## Initialize a project

Run from the project root:

```bash
loci init
```

This creates `.lociaction/` (including `memory.db` and `config.toml`), writes a short reminder into `AGENTS.md`, and installs Claude Code hooks unless `--no-hooks` is passed. If init fails partway through, a newly created `.lociaction/` is removed so re-running is safe.

When past session logs already exist, init asks:

1. **Min chars threshold** — index-time filter (default 50). Shorter exchanges are skipped.
2. **Existing exchanges** — skip all, distill last 50, distill all, or a custom count. Distilling history spends tokens on the chosen client.
3. **Run distillation now?**
4. **Distill client** — lists clients that are actually ready on this machine.

Invalid prompt input is rejected and asked again.

## Non-interactive setup

Skip prompts when an agent or script is driving init:

```bash
loci init --distill-client claude-cli --no-local-distiller --no-hooks --skip-existing
```

Useful flags:

| Flag | Effect |
| --- | --- |
| `--distill-client ID` | Select the distill client without prompting |
| `--no-local-distiller` | Do not offer `ollama pull` of the bundled local model |
| `--no-hooks` | Skip Claude Code hook registration |
| `--skip-existing` | Do not distill already-indexed exchanges |
| `--distill-limit N` | Distill only the most recent N existing exchanges |
| `--min-chars N` | Set the index-time character filter without prompting |

Valid client ids: `claude-cli`, `codex-cli`, `gemini-cli`, `grok-cli`, `opencode-cli`, `omp-cli`, `ollama-ft`, `openai-compat`.

After init:

```bash
loci index
loci distill --setup    # if the client was left unconfigured
loci status
```

## Next documents

- `loci docs show recall` — which lookup command to run
- `loci docs show harnesses` — session sources and lifecycle hooks
- `loci docs show distillation` — client choice, billing, local models
- `loci docs show troubleshooting` — init, index, hook, server, and distill failures
- `loci docs show privacy` — raw transcripts and credentials
