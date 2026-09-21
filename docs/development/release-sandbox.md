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

**Network requirement**: `_install_wheel()` installs the built wheel into
each scenario's fresh venv with a plain `uv pip install` — no `--offline`.
An earlier version used `--offline`, assuming the outer project's `uv sync
--extra dev` cache would satisfy it; it doesn't reliably, because a fresh
`uv pip install` into an unrelated venv is its own independent resolution
pass and isn't guaranteed to find every requirement (e.g. narrowly-pinned
`tree-sitter-c-sharp`) in whatever cache state that unrelated sync left
behind. This broke a real `publish.yml` run on a fresh Linux CI runner even
though the outer `uv sync --extra dev` step had already succeeded in the
same job. `make e2e` therefore needs outbound network access for this one
`uv pip install`; hermeticity here is about faking Claude/the embedder, not
about denying `uv` package resolution.

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
   ("No — distill on next session start"). Only 2 of the fixture's 7
   indexed exchanges are actually eligible for distillation (the rest are
   single-exchange conversations), so requesting "1" exercises a genuine
   partial skip with a priority choice inside that eligible pool. Verifies
   the exact pending/skipped split and that no distillation runs during
   `init` itself.
4. **`test_installed_wheel_scripted_setup_via_flags_only`** — a user
   scripting CI/onboarding drives every choice through flags
   (`--no-hooks --no-local-distiller --min-chars --distill-limit
   --distill-client`) with no interactive prompts beyond the unavoidable
   "run now" confirmation. Verifies no hook is installed, non-Claude harnesses
   still get explicit `loci hook install --harness <name>` guidance, and the
   same read-command surface works afterward.
5. **`test_installed_wheel_deferred_distill_runs_later`** — proves the
   "deferred" path from scenario 3 actually completes: after `init` defers
   distillation, a separate `loci distill` invocation is run and its
   result is checked. This scenario **discovered and pins the fix for** a
   real product inconsistency: `init`'s custom-count selection used to
   sort candidates purely by character length, with no notion of
   single-exchange-conversation eligibility, while `distill_all`
   unconditionally re-skips single-exchange conversations regardless of
   length — so a user told "N will be distilled" could see fewer than N
   actually distilled. `init` now pre-filters ineligible exchanges before
   the count/priority selection runs (see the eligibility pre-filter in
   `src/lociaction/cli/__init__.py`, right after "Indexed N existing
   exchange(s)..."). This test asserts the promised count and the actual
   distilled count now match exactly.
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

