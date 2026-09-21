"""Hermetic release-sandbox test against a freshly built, installed wheel.

The test never reads a real agent session, model cache, or home-directory setting.
It materializes every supported harness's synthetic history beneath a temporary
HOME, routes distillation and embeddings to deterministic local fakes, then
exercises the installed ``loci`` console script as a user would.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import tomllib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import pytest

_REPO_ROOT = Path(__file__).parents[2]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "harness_logs"
_EMBEDDING_DIMENSIONS = 384


def _run(
    args: list[str], *, cwd: Path, env: dict[str, str], input: str | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"command failed: {' '.join(args)}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result


def _write_jsonl_fixture(name: str, destination: Path, project: Path) -> None:
    """Install an in-scope JSONL fixture, including Claude's root metadata."""
    text = (
        (_FIXTURE_DIR / name)
        .read_text(encoding="utf-8")
        .replace('"/repo', f'"{project}')
        .replace(
            "fs.list_dir を Result 型にして", "fs.list_dir を Result 型にして。" * 4
        )
        .replace("list_dir を Result 型にして", "list_dir を Result 型にして。" * 4)
        .replace("list_dir を編集します。", "list_dir を編集します。" * 4)
    )
    records = [json.loads(line) for line in text.splitlines()]
    if name == "claude.jsonl":
        # Claude's fixture retains the real transcript shape, which predates a
        # top-level cwd. Discovery deliberately rejects such old logs, so add
        # the current root only in this sandbox copy.
        records[0]["cwd"] = str(project)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _write_distillable_claude_session(destination: Path, project: Path) -> None:
    """Create a two-exchange session; single-exchange sessions are skipped."""
    long_user = "list_dir を Result 型にして。" * 6
    long_agent = "list_dir を Result 型へ安全に移行しました。" * 6
    records = [
        {
            "type": "user",
            "uuid": "sandbox-user-1",
            "parentUuid": None,
            "isMeta": False,
            "timestamp": "2026-08-02T00:00:00.000Z",
            "cwd": str(project),
            "message": {"role": "user", "content": long_user},
        },
        {
            "type": "assistant",
            "uuid": "sandbox-assistant-1",
            "parentUuid": "sandbox-user-1",
            "timestamp": "2026-08-02T00:00:01.000Z",
            "message": {"role": "assistant", "content": long_agent},
        },
        {
            "type": "user",
            "uuid": "sandbox-user-2",
            "parentUuid": "sandbox-assistant-1",
            "isMeta": False,
            "timestamp": "2026-08-02T00:00:02.000Z",
            "cwd": str(project),
            "message": {"role": "user", "content": long_user},
        },
        {
            "type": "assistant",
            "uuid": "sandbox-assistant-2",
            "parentUuid": "sandbox-user-2",
            "timestamp": "2026-08-02T00:00:03.000Z",
            "message": {"role": "assistant", "content": long_agent},
        },
    ]
    destination.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _write_opencode_fixture(db_file: Path, project: Path) -> None:
    """Materialize the reviewed JSON fixture as OpenCode's on-disk SQLite DB."""
    fixture = json.loads(
        (_FIXTURE_DIR / "opencode.json")
        .read_text(encoding="utf-8")
        .replace("/repo", str(project))
        .replace(
            "fs.list_dir を Result 型にして", "fs.list_dir を Result 型にして。" * 4
        )
        .replace("list_dir を編集します。", "list_dir を編集します。" * 4)
    )
    db_file.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_file)
    try:
        con.executescript(
            """
            CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT NOT NULL, vcs TEXT, name TEXT);
            CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, directory TEXT NOT NULL);
            CREATE TABLE message (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL
            );
            CREATE TABLE part (
                id TEXT PRIMARY KEY, message_id TEXT NOT NULL, session_id TEXT NOT NULL,
                time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL
            );
            """
        )
        record = fixture["project"]
        con.execute(
            "INSERT INTO project (id, worktree, vcs, name) VALUES (?, ?, ?, ?)",
            (record["id"], record["worktree"], record["vcs"], record["name"]),
        )
        record = fixture["session"]
        con.execute(
            "INSERT INTO session (id, project_id, directory) VALUES (?, ?, ?)",
            (record["id"], record["project_id"], record["directory"]),
        )
        for message in fixture["messages"]:
            con.execute(
                "INSERT INTO message (id, session_id, time_created, time_updated, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    message["id"],
                    message["session_id"],
                    message["time_created"],
                    message["time_created"],
                    json.dumps(message["data"]),
                ),
            )
        for part in fixture["parts"]:
            con.execute(
                "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    part["id"],
                    part["message_id"],
                    part["session_id"],
                    part["time_created"],
                    part["time_created"],
                    json.dumps(part["data"]),
                ),
            )
        con.commit()
    finally:
        con.close()


def _write_harness_histories(home: Path, project: Path) -> None:
    claude_slug = re.sub(r"[^a-zA-Z0-9]", "-", str(project))
    _write_jsonl_fixture(
        "claude.jsonl",
        home / ".claude" / "projects" / claude_slug / "session-synthetic.jsonl",
        project,
    )
    _write_distillable_claude_session(
        home / ".claude" / "projects" / claude_slug / "distillable-synthetic.jsonl",
        project,
    )
    _write_jsonl_fixture(
        "codex.jsonl",
        home / ".codex" / "sessions" / "2026" / "rollout-synthetic.jsonl",
        project,
    )
    omp_slug = "-" + "-".join(project.relative_to(home).parts)
    _write_jsonl_fixture(
        "omp_pi.jsonl",
        home / ".omp" / "agent" / "sessions" / omp_slug / "session-synthetic.jsonl",
        project,
    )
    _write_jsonl_fixture(
        "grok.jsonl",
        home
        / ".grok"
        / "sessions"
        / quote(str(project), safe="")
        / "session-synthetic"
        / "updates.jsonl",
        project,
    )
    _write_opencode_fixture(
        home / ".local" / "share" / "opencode" / "opencode.db", project
    )


def _write_fake_claude(binary_dir: Path) -> None:
    binary_dir.mkdir()
    script = binary_dir / "claude"
    script.write_text(
        """#!/bin/sh
if [ \"${1:-}\" = \"--version\" ]; then
  echo \"claude sandbox 1.0\"
  exit 0
fi
cat >/dev/null
printf '%s\\n' '{\"structured_output\":{\"exchange_core\":\"Converted list_dir to Result\",\"specific_context\":\"list_dir\",\"room_assignments\":[{\"room_type\":\"concept\",\"room_key\":\"result-type\",\"room_label\":\"Result type migration\",\"relevance\":1.0}]}}'
""",
        encoding="utf-8",
    )
    script.chmod(0o755)


@contextmanager
def _fake_embedding_server(sock_path: Path) -> Iterator[None]:
    """Serve deterministic vectors through the production Unix-socket protocol."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen()
    server.settimeout(0.1)
    stopping = threading.Event()

    def serve() -> None:
        response = (
            json.dumps({"embedding": [0.125] * _EMBEDDING_DIMENSIONS}) + "\n"
        ).encode()
        while not stopping.is_set():
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            with connection:
                connection.recv(65_536)
                connection.sendall(response)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopping.set()
        thread.join(timeout=2)
        server.close()
        sock_path.unlink(missing_ok=True)


def _build_wheel(dist_dir: Path) -> Path:
    _run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        cwd=_REPO_ROOT,
        env=dict(os.environ),
    )
    return next(dist_dir.glob("*.whl"))


def _install_wheel(sandbox: Path, wheel: Path) -> Path:
    """Install a built wheel into a fresh, offline runtime environment."""
    venv = sandbox / "venv"
    _run(
        ["uv", "venv", "--python", sys.executable, str(venv)],
        cwd=sandbox,
        env=dict(os.environ),
    )
    python = venv / "bin" / "python"
    _run(
        ["uv", "pip", "install", "--offline", "--python", str(python), str(wheel)],
        cwd=sandbox,
        env=dict(os.environ),
    )
    return venv / "bin" / "loci"


@pytest.fixture(scope="module")
def installed_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One built artifact; every scenario still receives a fresh venv and HOME."""
    return _build_wheel(tmp_path_factory.mktemp("release-wheel") / "dist")


@dataclass(frozen=True)
class UserSandbox:
    home: Path
    project: Path
    loci: Path
    env: dict[str, str]
    sock_path: Path


def _prepare_user_sandbox(tmp_path: Path, wheel: Path) -> UserSandbox:
    sandbox = tmp_path / "sandbox"
    home = sandbox / "home"
    project = home / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "fs.py").write_text(
        "def list_dir(path):\n    return []\n", encoding="utf-8"
    )
    (project / "src" / "result.py").write_text(
        "class Result:\n    pass\n", encoding="utf-8"
    )
    (project / "src" / "legacy.py").write_text("x = 1\n", encoding="utf-8")
    (project / "src" / "new_name.py").write_text("x = 2\n", encoding="utf-8")
    _run(["git", "init", "-q"], cwd=project, env=dict(os.environ))
    _write_harness_histories(home, project)
    loci = _install_wheel(sandbox, wheel)
    fake_bin = sandbox / "bin"
    _write_fake_claude(fake_bin)
    sock_path = Path("/tmp") / f"loci-e2e-{uuid.uuid4().hex}.sock"
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "LOCIACTION_REMOTE_DISTILL_CLIENTS": "claude-cli",
            "LOCIACTION_SOCK_PATH": str(sock_path),
            "NO_COLOR": "1",
            "PATH": os.pathsep.join(
                (str(fake_bin), str(loci.parent), "/usr/bin", "/bin")
            ),
        }
    )
    env.pop("PYTHONPATH", None)
    return UserSandbox(home, project, loci, env, sock_path)


@pytest.mark.e2e
def test_installed_wheel_user_distills_all_during_onboarding(
    tmp_path: Path, installed_wheel: Path
) -> None:
    """A new user accepts default threshold, all history, and immediate distill."""
    sandbox = _prepare_user_sandbox(tmp_path, installed_wheel)

    with _fake_embedding_server(sandbox.sock_path):
        init = _run(
            [str(sandbox.loci), "init"],
            cwd=sandbox.project,
            env=sandbox.env,
            # threshold default → distill all → run now → source=Claude → model=default
            input="1\n3\n2\n2\n1\n",
        )
        assert "Min chars threshold" in init.stdout
        assert "Found" in init.stdout
        assert "Start distillation now?" in init.stdout
        assert "Running distillation..." in init.stdout
        assert "Distilled" in init.stdout

        status = json.loads(
            _run(
                [str(sandbox.loci), "status", "--check", "--json"],
                cwd=sandbox.project,
                env=sandbox.env,
            ).stdout
        )
        assert status["exchanges"] >= 7
        assert status["distilled"] >= 2, init.stdout + init.stderr
        assert status["palace_objects"] == status["distilled"]
        assert status["skipped"] >= 5
        # Regression guard: resolver.py unconditionally imports tree-sitter
        # language bindings (including tree-sitter-c-sharp) at module load.
        # A missing/removed dependency declaration breaks this import for
        # every language, not just C#; symbols > 0 proves it actually
        # resolved in the freshly installed, isolated wheel environment.
        assert status["symbols"] > 0, init.stdout + init.stderr
        assert status["distill_client"] == "claude-cli"
        assert status["distill_available"] is True
        settings = (sandbox.home / ".claude" / "settings.json").read_text(
            encoding="utf-8"
        )
        assert "loci index" in settings

        search = json.loads(
            _run(
                [str(sandbox.loci), "search", "list_dir", "--json"],
                cwd=sandbox.project,
                env=sandbox.env,
            ).stdout
        )
        assert search
        exchange_id = search[0]["exchange_id"]
        shown = json.loads(
            _run(
                [str(sandbox.loci), "show", exchange_id, "--json"],
                cwd=sandbox.project,
                env=sandbox.env,
            ).stdout
        )
        assert shown["exchange_id"] == exchange_id
        assert "list_dir" in shown["agent_content"]

        context = json.loads(
            _run(
                [str(sandbox.loci), "context", "src/fs.py:list_dir", "--json"],
                cwd=sandbox.project,
                env=sandbox.env,
            ).stdout
        )
        assert context
        assert context[0]["file_path"] == "src/fs.py"
        recalled = json.loads(
            _run(
                [str(sandbox.loci), "recall", "list_dir", "--json"],
                cwd=sandbox.project,
                env=sandbox.env,
            ).stdout
        )
        assert recalled
        assert _run(
            [str(sandbox.loci), "docs", "list", "--json"],
            cwd=sandbox.project,
            env=sandbox.env,
        ).stdout
        assert (
            "GC complete"
            in _run(
                [str(sandbox.loci), "gc"], cwd=sandbox.project, env=sandbox.env
            ).stdout
        )
        assert (
            "Nothing new to index."
            in _run(
                [str(sandbox.loci), "index"], cwd=sandbox.project, env=sandbox.env
            ).stdout
        )


@pytest.mark.e2e
def test_installed_wheel_user_skips_existing_history(
    tmp_path: Path, installed_wheel: Path
) -> None:
    """A user declines history distillation but still chooses a future client."""
    sandbox = _prepare_user_sandbox(tmp_path, installed_wheel)

    init = _run(
        [str(sandbox.loci), "init"],
        cwd=sandbox.project,
        env=sandbox.env,
        # threshold default → skip all → source=Claude → model=default
        input="1\n1\n2\n1\n",
    )
    assert "Skip all" in init.stdout
    assert "Start distillation now?" not in init.stdout
    assert "Marked" in init.stdout
    status = json.loads(
        _run(
            [str(sandbox.loci), "status", "--check", "--json"],
            cwd=sandbox.project,
            env=sandbox.env,
        ).stdout
    )
    assert status["skipped"] == status["exchanges"]
    assert status["pending"] == 0
    config = tomllib.loads(
        (sandbox.project / ".lociaction" / "config.toml").read_text(encoding="utf-8")
    )
    assert config["distill"]["client"] == "claude-cli"
    assert config["index"]["min_chars"] == 50
    assert (sandbox.home / ".claude" / "settings.json").exists()


@pytest.mark.e2e
def test_installed_wheel_user_distills_custom_recent_history_later(
    tmp_path: Path, installed_wheel: Path
) -> None:
    """A user chooses a custom count, longest-first policy, and deferred run."""
    sandbox = _prepare_user_sandbox(tmp_path, installed_wheel)

    init = _run(
        [str(sandbox.loci), "init"],
        cwd=sandbox.project,
        env=sandbox.env,
        # threshold default → custom 2 → longest → run later → source=Claude → model=default
        input="1\n4\n2\n2\n1\n2\n1\n",
    )
    assert "Custom" in init.stdout
    assert "Distill priority" in init.stdout
    assert "Start distillation now?" in init.stdout
    assert "Running distillation..." not in init.stdout
    status = json.loads(
        _run(
            [str(sandbox.loci), "status", "--check", "--json"],
            cwd=sandbox.project,
            env=sandbox.env,
        ).stdout
    )
    assert status["pending"] == 2
    assert status["skipped"] == status["exchanges"] - 2


@pytest.mark.e2e
def test_installed_wheel_scripted_setup_via_flags_only(
    tmp_path: Path, installed_wheel: Path
) -> None:
    """A user scripting CI/onboarding drives every choice via flags, no TTY."""
    sandbox = _prepare_user_sandbox(tmp_path, installed_wheel)

    with _fake_embedding_server(sandbox.sock_path):
        init = _run(
            [
                str(sandbox.loci),
                "init",
                "--no-hooks",
                "--no-local-distiller",
                "--min-chars",
                "50",
                "--distill-limit",
                "1000",
                "--distill-client",
                "claude-cli",
            ],
            cwd=sandbox.project,
            env=sandbox.env,
            input="yes\n",
        )
        assert "Min chars threshold" not in init.stdout
        assert "Available distillation sources" not in init.stdout
        assert "Indexed" in init.stdout
        assert "Distilled" in init.stdout
        assert "Hooks installed" not in init.stdout
        assert "Native hooks are available" not in init.stdout
        assert not (sandbox.home / ".claude" / "settings.json").exists()

        status = json.loads(
            _run(
                [str(sandbox.loci), "status", "--check", "--json"],
                cwd=sandbox.project,
                env=sandbox.env,
            ).stdout
        )
        assert status["exchanges"] >= 7
        assert status["distilled"] >= 2, init.stdout + init.stderr
        assert status["skipped"] >= 5
        assert status["symbols"] > 0, init.stdout + init.stderr
        assert status["palace_objects"] == status["distilled"]
        assert status["distill_client"] == "claude-cli"
        assert status["distill_available"] is True

        search = json.loads(
            _run(
                [str(sandbox.loci), "search", "list_dir", "--json"],
                cwd=sandbox.project,
                env=sandbox.env,
            ).stdout
        )
        assert search
        exchange_id = search[0]["exchange_id"]
        shown = json.loads(
            _run(
                [str(sandbox.loci), "show", exchange_id, "--json"],
                cwd=sandbox.project,
                env=sandbox.env,
            ).stdout
        )
        assert shown["exchange_id"] == exchange_id
        assert "list_dir" in shown["agent_content"]

        context = json.loads(
            _run(
                [str(sandbox.loci), "context", "src/fs.py:list_dir", "--json"],
                cwd=sandbox.project,
                env=sandbox.env,
            ).stdout
        )
        assert context
        assert context[0]["file_path"] == "src/fs.py"

        recalled = json.loads(
            _run(
                [str(sandbox.loci), "recall", "list_dir", "--json"],
                cwd=sandbox.project,
                env=sandbox.env,
            ).stdout
        )
        assert recalled
        assert _run(
            [str(sandbox.loci), "docs", "list", "--json"],
            cwd=sandbox.project,
            env=sandbox.env,
        ).stdout
        assert (
            "GC complete"
            in _run(
                [str(sandbox.loci), "gc"], cwd=sandbox.project, env=sandbox.env
            ).stdout
        )
        assert (
            "Nothing new to index."
            in _run(
                [str(sandbox.loci), "index"], cwd=sandbox.project, env=sandbox.env
            ).stdout
        )


@pytest.mark.e2e
def test_installed_wheel_deferred_distill_runs_later(
    tmp_path: Path, installed_wheel: Path
) -> None:
    """A user who deferred distillation runs `loci distill` afterward and it
    actually completes the pending exchanges — not just marks them pending."""
    sandbox = _prepare_user_sandbox(tmp_path, installed_wheel)

    init = _run(
        [str(sandbox.loci), "init"],
        cwd=sandbox.project,
        env=sandbox.env,
        # threshold default → custom 2 → longest → run later → source=Claude → model=default
        input="1\n4\n2\n2\n1\n2\n1\n",
    )
    assert "Start distillation now?" in init.stdout
    assert "Running distillation..." not in init.stdout

    before = json.loads(
        _run(
            [str(sandbox.loci), "status", "--check", "--json"],
            cwd=sandbox.project,
            env=sandbox.env,
        ).stdout
    )
    assert before["pending"] == 2
    assert before["distilled"] == 0

    with _fake_embedding_server(sandbox.sock_path):
        distill = _run(
            [str(sandbox.loci), "distill"], cwd=sandbox.project, env=sandbox.env
        )
    # Discovered discrepancy: `init`'s "longest" custom-count selection
    # (src/lociaction/cli/__init__.py::_resolve_skip_count) sorts candidates
    # purely by LENGTH(user_content)+LENGTH(agent_content) and has no notion
    # of single-exchange-conversation eligibility. `distill_all`
    # (src/lociaction/distiller.py) unconditionally re-skips any
    # single-exchange-conversation exchange regardless of length. Kept-2 here
    # includes the fixture's single longest exchange (a one-exchange Codex
    # session), which `distill_all` immediately re-marks skipped — so only 1
    # of the "2 will be distilled" `init` promised actually gets distilled.
    # This is real observed product behavior, not a test assumption; it's a
    # known init/distill selection-criteria mismatch worth a product decision.
    assert "Distilled 1 exchange(s)." in distill.stdout, distill.stdout + distill.stderr

    after = json.loads(
        _run(
            [str(sandbox.loci), "status", "--check", "--json"],
            cwd=sandbox.project,
            env=sandbox.env,
        ).stdout
    )
    assert after["pending"] == 0
    assert after["distilled"] == 1
    assert after["skipped"] == before["skipped"] + 1
    assert after["palace_objects"] == 1
    assert after["symbols"] > 0, distill.stdout + distill.stderr


@pytest.mark.e2e
def test_installed_wheel_hook_install_writes_non_claude_native_files(
    tmp_path: Path, installed_wheel: Path
) -> None:
    """`loci hook install --harness <name>` actually writes each harness's
    native lifecycle file — not just the guidance text `init` prints for it.

    Covers both file-ownership models: Codex shares a merged JSON settings
    file (like Claude/Grok); Oh My Pi owns a single dedicated `.ts` file
    (like OpenCode).
    """
    sandbox = _prepare_user_sandbox(tmp_path, installed_wheel)
    _run(
        [str(sandbox.loci), "init", "--no-hooks", "--no-local-distiller"],
        cwd=sandbox.project,
        env=sandbox.env,
        input="1\n1\n1\n1\n",
    )

    codex_result = _run(
        [str(sandbox.loci), "hook", "install", "--harness", "codex"],
        cwd=sandbox.project,
        env=sandbox.env,
    )
    codex_hooks_path = sandbox.home / ".codex" / "hooks.json"
    assert f"Hooks installed: {codex_hooks_path}" in codex_result.stdout
    codex_settings = json.loads(codex_hooks_path.read_text(encoding="utf-8"))
    stop_commands = [
        hook["command"]
        for entry in codex_settings["hooks"]["Stop"]
        for hook in entry["hooks"]
    ]
    assert any("loci index --harness codex" in cmd for cmd in stop_commands)

    omp_result = _run(
        [str(sandbox.loci), "hook", "install", "--harness", "omp-pi"],
        cwd=sandbox.project,
        env=sandbox.env,
    )
    omp_ts_path = sandbox.home / ".omp" / "agent" / "extensions" / "lociaction.ts"
    assert f"Hooks installed: {omp_ts_path}" in omp_result.stdout
    omp_content = omp_ts_path.read_text(encoding="utf-8")
    assert "LOCIACTION_HOOK_MARKER" in omp_content
    assert "loci index --harness omp-pi" in omp_content

    # Re-running install is idempotent, matching the writers' own contract.
    repeat = _run(
        [str(sandbox.loci), "hook", "install", "--harness", "codex"],
        cwd=sandbox.project,
        env=sandbox.env,
    )
    assert "already up to date" in repeat.stdout

    uninstall = _run(
        [str(sandbox.loci), "hook", "uninstall", "--harness", "omp-pi"],
        cwd=sandbox.project,
        env=sandbox.env,
    )
    assert f"Hooks uninstalled: {omp_ts_path}" in uninstall.stdout
    assert not omp_ts_path.exists()
