# Release Sandbox

`make e2e` runs the release-grade, hermetic command-line workflow:

```bash
make e2e
```

It builds the current source tree into a wheel, installs that wheel in a fresh
virtual environment, and invokes only the installed `loci` executable. The
sandbox has its own temporary `HOME`, project repository, fake harness history,
fake Claude CLI, and deterministic embedding socket. It never reads or writes
your actual agent sessions, model configuration, hooks, or `.lociaction/`
state.

`tests/e2e/` is marked `e2e` in `pyproject.toml` and is **excluded from the
default test run** — `make test`, `make check`, and `.github/workflows/ci.yml`'s
"Run tests" step all pass `-m "not e2e"`. It builds
and installs a wheel per scenario, which is too slow and too heavy
(network-adjacent package resolution, a fresh venv per test) to run on every
push. `.github/workflows/publish.yml` runs `make e2e` automatically as a gate
before every release-tag publish, so a failing sandbox blocks the release.
Still run `make e2e` locally before pushing a release tag — publish.yml
catching it means the tag already exists and the human release-tag approval
`AGENTS.md` requires already happened; catching it locally is strictly
cheaper. Also run it whenever a bug needs reproduction through the real
installed command boundary.

**Cache invariant**: `uv pip install --offline` succeeds only because `uv
sync --extra dev` already populated the local `uv` cache with every wheel
`pyproject.toml` currently declares, including narrowly-pinned ones like
`tree-sitter-c-sharp`. Run `uv sync --extra dev` first (once per environment,
or after any dependency change) if `make e2e` fails with a `--offline`
resolution error — that failure means the cache is stale or a new dependency
was added without a matching sync, not that the sandbox itself is broken.

## Covered journey

The sandbox materializes reviewed synthetic histories for every supported
harness—Claude Code, Codex, Grok, Oh My Pi, and OpenCode—beneath a shared,
once-per-run built wheel (`installed_wheel` fixture), then each scenario gets
its own fresh `HOME`/project/venv install from that artifact. Six scenarios
drive `loci init` and its follow-on commands through distinct real user
decision paths:

1. **`test_installed_wheel_user_distills_all_during_onboarding`** — a new user
   accepts every default interactively: default threshold, "Distill all",
   "Yes — run now", the Claude Code harness source, and its default model.
   Verifies initial distillation actually runs and every read command
   (`status --check`, `search`, `show`, `context`, `recall`, `docs`, `gc`,
   repeat `index`) works against the installed artifact afterward.
2. **`test_installed_wheel_user_skips_existing_history`** — a user declines to
   distill any past history ("Skip all") but still picks a client for future
   sessions. Verifies every exchange is marked skipped (never pending), and
   `config.toml` is parsed with `tomllib` (not a substring match, which would
   false-positive against the commented-out placeholder client lines) to
   confirm the real `[distill] client` and `[index] min_chars` values.
3. **`test_installed_wheel_user_distills_custom_recent_history_later`** — a
   user picks "Custom" count, "Longest" priority, and defers distillation
   ("No — distill on next session start"). Verifies the exact pending/skipped
   split and that no distillation runs during `init` itself.
4. **`test_installed_wheel_scripted_setup_via_flags_only`** — a user
   scripting CI/onboarding drives every choice through flags
   (`--no-hooks --no-local-distiller --min-chars --distill-limit
   --distill-client`) with no interactive prompts beyond the unavoidable
   "run now" confirmation. Verifies no hook is installed, non-Claude harnesses
   still get explicit `loci hook install --harness <name>` guidance, and the
   same read-command surface works afterward.
5. **`test_installed_wheel_deferred_distill_runs_later`** — proves the
   "deferred" path from scenario 3 actually completes: after `init` defers
   distillation, a separate `loci distill` invocation is run and its result
   is checked. This scenario **discovered a real product inconsistency**:
   `init`'s "longest" custom-count selection sorts purely by character
   length and has no notion of single-exchange-conversation eligibility,
   while `distill_all` unconditionally re-skips single-exchange conversations
   regardless of length. A user who is told "N will be distilled" can
   therefore see fewer than N actually distilled once they run `loci
   distill`. The test documents and asserts the current (surprising) count;
   see the inline comment for the exact mismatch and the two source
   locations involved if this gets reconciled.
6. **`test_installed_wheel_hook_install_writes_non_claude_native_files`** —
   runs `loci hook install --harness codex` (merged-JSON file model, shared
   with Grok) and `--harness omp-pi` (dedicated-file model, shared with
   OpenCode) for real, asserting the native hook file each writes, its
   content, idempotent re-install, and uninstall — not just the guidance text
   `init --no-hooks` prints for these harnesses.

Every scenario's exact interactive input sequence was captured by manually
reproducing the CLI against a real built wheel and reading its literal
prompts—`select_index`'s 1-based menu order shifts based on which clients are
"ready" versus "setupable" (e.g. `llamacpp-ft` always appears first and
"needs setup" in a hermetic sandbox with no `llama-server`/`brew` on `PATH`).
Never guess prompt ordinals from source reading alone; a wrong ordinal
silently selects a different menu item instead of failing loudly.

External dependencies are faked only at their process/socket boundaries: a
fake `claude` script answers `--print`/`--version`, and a fake Unix-socket
server answers the embedder's wire protocol. `PATH` is deliberately narrowed
to just the fake binaries plus `/usr/bin:/bin` so `shutil.which("brew")`
cannot find a real Homebrew and accidentally trigger a live
`brew install llama.cpp` — selecting the local FT client always fails
cleanly with "llama-server not found" in this sandbox, exactly as it should
off a hermetic `PATH`.

Run it before release publication and whenever a bug needs reproduction
through the real command boundary. Add a focused scenario to
`tests/e2e/test_installed_cli_sandbox.py` when the regression spans commands,
installation, harness discovery, interactive prompt ordering, or persistent
state. Keep unit tests for narrow parser and domain invariants; do not add
real session logs or credentials to this sandbox.

## Not covered

This sandbox intentionally does not exercise: real provider authentication,
billing, or network calls to Claude/Codex/Gemini/Grok/OpenCode/Oh My Pi; real
embedding model quality, download, or GPU/CPU performance; hook
install/uninstall for Claude or Grok (only Codex and Oh My Pi are exercised,
one per file-ownership model — Claude has its own dedicated unit tests in
`tests/test_status_hook.py`, and Grok shares Codex's merged-JSON writer);
publishing to PyPI itself, or a post-publish install from the real PyPI
index; or per-harness log-parsing edge cases and corruption handling, which
remain the responsibility of each adapter's own unit and regression tests.

