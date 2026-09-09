# Lociaction Agent Guide

This is the canonical guide for agents working in this repository. `CLAUDE.md` links here so every supported agent reads the same instructions.

## Purpose

`Lociaction` is a local-first memory layer for AI coding agents. The `loci` CLI indexes agent-session logs, records code touches, and recalls prior decisions through code-aware and semantic lookup.

The primary user is the agent itself, not a human. Prefer the narrowest recall command that matches the available context before editing unfamiliar code.

## Recall Before Editing

```bash
# Preferred: recover the history of the exact symbol or selected line.
loci context <file>:<symbol> --json
loci context <file>:<line> --json

# Use when only the file is known.
loci context <file> --json

# Use when no code location is known yet.
loci search "query" --json --limit 5

# Recover work associated with a branch.
loci context --branch NAME --json
```

Use `loci recall --file PATH --branch NAME --json` at session start when both a code location and branch are known. It merges code-anchored context with semantic results, favoring recent decisions.

## CLI Surface

```bash
loci init [--distill-client ID]               # Initialize .lociaction/ in the project root
loci index [--harness NAME] [--path PATH]     # Index session logs; default detects every harness
loci distill [--limit N] [--setup]            # Distill queued exchanges with the configured client
loci search "query" --json --limit 5          # Semantic recall over distilled conversations
loci context <file>:<symbol> --json           # Code location → prior conversations
loci context --branch NAME --json              # Branch → prior conversations
loci recall --file PATH --branch NAME --json  # Session-start composite recall
loci show "<exchange-id>" --json              # Read a stored verbatim exchange
loci status                                   # Inspect index and distillation status
loci gc                                       # Remove orphaned data while retaining backups
loci hook install --harness NAME               # Install native lifecycle integration
loci hook uninstall --harness NAME             # Remove native lifecycle integration
loci eval gate --json                          # Run the symbol-recall regression gate
```

`loci init` writes the shared agent-instruction marker to `AGENTS.md`. It may offer a local Ollama distiller and then selects one detected distillation client. Pass `--no-local-distiller` to suppress the Ollama offer, or `--distill-client <id>` for non-interactive setup.

## Harnesses and Distillation

Supported session-log harnesses: Claude Code, Codex CLI, Grok, Oh My Pi, and OpenCode. All have native lifecycle installation through `loci hook install --harness <name>`.

Distillation is independent of the source harness. One configured client processes all undistilled exchanges. Supported client identifiers are:

```text
claude-cli  codex-cli  gemini-cli  grok-cli  opencode-cli  omp-cli
ollama-ft   openai-compat
```

Use a configured local model when token cost or data locality matters. Do not trigger paid distillation merely to make a test pass.

## Architecture

```text
session logs
  → harness adapter
  → core ingest
  → SQLite exchanges, code touches, code symbols, and code edges
  → optional distillation into palace objects
  → BM25 + HNSW reciprocal-rank-fusion recall
```

`src/lociaction/adapters/harness/` owns harness-specific log parsing, code-touch extraction, and lifecycle integration. `src/lociaction/adapters/model/` owns distillation-client discovery and transport selection. Keep `core/` independent of any specific harness or model client.

## Repository Layout

```text
src/lociaction/
├── cli/              # Typer command layer
├── adapters/         # Harness and model integrations
├── core/             # Ports, domain models, and ingest orchestration
├── db.py             # SQLite schema, migrations, and persistence
├── indexer.py        # Exchange indexing pipeline
├── distiller.py      # Palace-object distillation pipeline
├── search.py         # BM25, HNSW, and RRF search
├── context_lookup.py # Code-anchored reverse lookup
├── resolver.py       # tree-sitter symbol resolution
└── eval/             # Synthetic retrieval evaluation and regression gate
tests/                # Deterministic pytest coverage and synthetic fixtures
.github/workflows/    # CI and tag-triggered PyPI publication
```

## Development Rules

- Install development dependencies with `uv sync --extra dev`.
- Run `make check` before committing code changes. It runs Ruff, Pyright, and pytest.
- Run `uv run loci eval gate --json` when changing retrieval ranking, code edges, or evaluation fixtures.
- Use synthetic fixtures in `tests/fixtures/`; never commit personal session logs, `.lociaction/`, or local model data.
- Preserve the current adapter and core boundaries. Do not introduce a second convention beside an existing abstraction.
- Migrate every caller when changing a public or cross-module contract; do not leave compatibility shims unless explicitly required.

## Release

`v*` tags trigger the production PyPI workflow through GitHub OIDC. Verify clean-clone checks and an installed-package smoke test before creating a release tag. Publishing a version to PyPI is irreversible; obtain explicit approval immediately before pushing a release tag.
