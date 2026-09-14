"""config.toml 読み込みのテスト"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from lociaction.config import (
    DEFAULT_DISTILL_BATCH_LIMIT,
    DEFAULT_DISTILL_MIN_CHARS,
    DEFAULT_DISTILL_MODEL,
    DEFAULT_DISTILL_PROVIDER,
    DEFAULT_INDEX_MIN_CHARS,
    LOCAL_DISTILL_BASE_URL,
    LOCAL_DISTILL_MODEL,
    Config,
    load_config,
)


def test_local_distill_model_uses_ollama_hf_pull_syntax() -> None:
    """LOCAL_DISTILL_MODEL は `ollama pull` がそのまま使える hf.co/<repo>:<quant> 形式"""
    assert LOCAL_DISTILL_MODEL == (
        "hf.co/sennaLLMLearner/qwen2.5-7b-memory-distiller:Q4_K_M"
    )
    assert LOCAL_DISTILL_BASE_URL == "http://localhost:11434/v1"


def test_load_config_no_file(tmp_path: Path) -> None:
    """config.toml がなければデフォルト"""
    (tmp_path / ".lociaction").mkdir()
    cfg = load_config(tmp_path)
    assert cfg.distill_model == DEFAULT_DISTILL_MODEL
    assert cfg.distill_batch_limit == DEFAULT_DISTILL_BATCH_LIMIT
    assert cfg.index_min_chars == DEFAULT_INDEX_MIN_CHARS


def test_load_config_custom_values(tmp_path: Path) -> None:
    """カスタム値が正しく読まれる"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text(
        '[distill]\nmodel = "claude-sonnet-4-20250514"\nbatch_limit = 10\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_model == "claude-sonnet-4-20250514"
    assert cfg.distill_batch_limit == 10


def test_load_config_partial(tmp_path: Path) -> None:
    """一部だけ設定した場合、残りはデフォルト"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[distill]\nbatch_limit = 5\n")
    cfg = load_config(tmp_path)
    assert cfg.distill_model == DEFAULT_DISTILL_MODEL
    assert cfg.distill_batch_limit == 5


def test_load_config_invalid_batch_limit_fallback(tmp_path: Path) -> None:
    """不正な batch_limit はデフォルトにフォールバック"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[distill]\nbatch_limit = -1\n")
    cfg = load_config(tmp_path)
    assert cfg.distill_batch_limit == DEFAULT_DISTILL_BATCH_LIMIT


def test_load_config_invalid_model_fallback(tmp_path: Path) -> None:
    """空文字のモデル名はデフォルトにフォールバック"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text('[distill]\nmodel = ""\n')
    cfg = load_config(tmp_path)
    assert cfg.distill_model == DEFAULT_DISTILL_MODEL


def test_load_config_broken_toml_fallback(tmp_path: Path) -> None:
    """壊れた TOML はデフォルト値にフォールバックしつつ、config_error に記録する
    （#26: 解析失敗を無言の Config() フォールバックにせず可視化する）"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("not valid toml [[[")
    cfg = load_config(tmp_path)
    assert cfg == Config(config_error=cfg.config_error)
    assert cfg.config_error is not None
    assert "config.toml" in cfg.config_error


def test_load_config_parse_error_sanitizes_terminal_output(
    tmp_path: Path, capsys
) -> None:
    """OSError/TOMLDecodeError の文字列は端末制御シーケンスを含みうる未信頼データ
    なので、warning・config_error のどちらにも生の ESC を残さない
    (LOCI-TERMINAL-SANITIZE-INCONSISTENT)。"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[distill]\n")
    with patch(
        "pathlib.Path.open",
        side_effect=OSError("crafted \x1b]8;;https://evil.test\x1b\\x error"),
    ):
        cfg = load_config(tmp_path)
    assert cfg.config_error is not None
    assert "\x1b" not in cfg.config_error
    assert "\x1b" not in capsys.readouterr().err


def test_load_config_deeply_nested_toml_falls_back_instead_of_crashing(
    tmp_path: Path,
) -> None:
    """攻撃者制御の config.toml が極端に深くネストしていても RecursionError で
    クラッシュせず、他の壊れた config と同じくデフォルトへフォールバックする
    (LOCI-CONFIG-TOML-RECURSION-DOS)。"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    depth = 4000
    deeply_nested = "[" * depth + "]" * depth
    (lociaction_dir / "config.toml").write_text(f"distill = {deeply_nested}\n")

    cfg = load_config(tmp_path)

    assert cfg == Config(config_error=cfg.config_error)
    assert cfg.config_error is not None



def test_load_config_oversized_file_falls_back_instead_of_crashing(
    tmp_path: Path,
) -> None:
    """攻撃者制御の config.toml が上限を超える場合、tomllib.load() で
    メモリを消費させず、他の壊れた config と同じくデフォルトへフォールバックする
    (LOCI-CONFIG-TOML-MEMORYERROR-DOS)。"""
    from lociaction.config import MAX_CONFIG_FILE_BYTES

    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    oversized_value = "x" * (MAX_CONFIG_FILE_BYTES + 1)
    (lociaction_dir / "config.toml").write_text(f'distill = "{oversized_value}"\n')

    cfg = load_config(tmp_path)

    assert cfg == Config(config_error=cfg.config_error)
    assert cfg.config_error is not None
    assert "exceeds" in cfg.config_error


def test_load_config_rejects_batch_limit_above_automatic_hook_cap(
    tmp_path: Path,
) -> None:
    """tracked config が自動 distill を全 pending exchange へ拡大できない
    （LOCI-CONFIG-UNBOUNDED-BATCH-01）。"""
    from lociaction.config import MAX_DISTILL_BATCH_LIMIT

    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text(
        f"[distill]\nbatch_limit = {MAX_DISTILL_BATCH_LIMIT + 1}\n"
    )

    cfg = load_config(tmp_path)

    assert cfg.distill_batch_limit == DEFAULT_DISTILL_BATCH_LIMIT

def test_load_config_index_min_chars(tmp_path: Path) -> None:
    """index.min_chars が正しく読まれる"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[index]\nmin_chars = 200\n")
    cfg = load_config(tmp_path)
    assert cfg.index_min_chars == 200


def test_load_config_invalid_min_chars_fallback(tmp_path: Path) -> None:
    """不正な min_chars はデフォルトにフォールバック"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[index]\nmin_chars = 0\n")
    cfg = load_config(tmp_path)
    assert cfg.index_min_chars == DEFAULT_INDEX_MIN_CHARS


def test_load_config_distill_min_chars(tmp_path: Path) -> None:
    """distill.min_chars が正しく読まれる"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[distill]\nmin_chars = 200\n")
    cfg = load_config(tmp_path)
    assert cfg.distill_min_chars == 200


def test_load_config_distill_min_chars_default(tmp_path: Path) -> None:
    """distill.min_chars 未設定時はデフォルト100"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[distill]\n")
    cfg = load_config(tmp_path)
    assert cfg.distill_min_chars == DEFAULT_DISTILL_MIN_CHARS


def test_load_config_distill_min_chars_invalid_fallback(tmp_path: Path) -> None:
    """不正な distill.min_chars はデフォルトにフォールバック"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[distill]\nmin_chars = -5\n")
    cfg = load_config(tmp_path)
    assert cfg.distill_min_chars == DEFAULT_DISTILL_MIN_CHARS


def test_load_config_toml_decode_error_fallback(tmp_path: Path, capsys) -> None:
    """不正な TOML 内容（TOMLDecodeError）はデフォルトにフォールバック、警告出力、
    config_error にも記録される"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("not valid toml [")
    cfg = load_config(tmp_path)
    assert cfg == Config(config_error=cfg.config_error)
    assert cfg.config_error is not None
    captured = capsys.readouterr()
    assert "Warning" in captured.err


def test_load_config_oserror_fallback(tmp_path: Path) -> None:
    """OSError（ファイルアクセスエラー）はデフォルトにフォールバック、
    config_error にも記録される"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    config_file = lociaction_dir / "config.toml"
    config_file.write_text("[distill]\nmodel = 'test'\n")
    # exists() は True のまま、open() だけ OSError を引き起こす
    with patch("pathlib.Path.open", side_effect=OSError("disk error")):
        cfg = load_config(tmp_path)
    assert cfg == Config(config_error=cfg.config_error)
    assert cfg.config_error is not None
    assert "disk error" in cfg.config_error


def test_load_config_provider_default(tmp_path: Path) -> None:
    """[distill] provider キーがないときはデフォルト"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[distill]\n")
    cfg = load_config(tmp_path)
    assert cfg.distill_provider == DEFAULT_DISTILL_PROVIDER
    assert cfg.distill_base_url is None


def test_load_config_provider_invalid_fallback(tmp_path: Path) -> None:
    """不正な provider はデフォルトにフォールバック"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[distill]\nprovider = 'badprovider'\n")
    cfg = load_config(tmp_path)
    assert cfg.distill_provider == DEFAULT_DISTILL_PROVIDER


def test_load_config_rejects_remote_base_url_without_explicit_opt_in(
    tmp_path: Path, capsys
) -> None:
    """プロジェクト設定だけでは会話をリモート endpoint へ送信させない。"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text(
        "[distill]\nprovider = 'openai'\nbase_url = 'https://api.example.test/v1'\n"
    )

    cfg = load_config(tmp_path)

    assert cfg.distill_provider == DEFAULT_DISTILL_PROVIDER
    assert cfg.distill_base_url is None
    assert "LOCIACTION_REMOTE_DISTILL_ORIGINS" in capsys.readouterr().err


def test_load_config_allows_remote_base_url_with_explicit_opt_in(
    tmp_path: Path, monkeypatch
) -> None:
    """ユーザー環境で明示 opt-in した場合だけリモート endpoint を使える。"""
    monkeypatch.setenv(
        "LOCIACTION_REMOTE_DISTILL_ORIGINS", "https://api.example.test"
    )
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text(
        "[distill]\nprovider = 'openai'\nbase_url = 'https://api.example.test/v1'\n"
    )

    cfg = load_config(tmp_path)

    assert cfg.distill_provider == "openai"
    assert cfg.distill_base_url == "https://api.example.test/v1"


def test_load_config_provider_openai_missing_base_url_fallback(tmp_path: Path) -> None:
    """provider = 'openai' だが base_url がない場合はデフォルトにフォールバック"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[distill]\nprovider = 'openai'\n")
    cfg = load_config(tmp_path)
    assert cfg.distill_provider == DEFAULT_DISTILL_PROVIDER
    assert cfg.distill_base_url is None


def test_load_config_provider_openai_empty_base_url_fallback(tmp_path: Path) -> None:
    """provider = 'openai' で base_url が空文字列の場合はデフォルトにフォールバック"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text(
        "[distill]\nprovider = 'openai'\nbase_url = ''\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_provider == DEFAULT_DISTILL_PROVIDER


def test_load_config_provider_claude_no_base_url(tmp_path: Path) -> None:
    """provider = 'claude' の場合は base_url は不要"""
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    (lociaction_dir / "config.toml").write_text("[distill]\nprovider = 'claude'\n")
    cfg = load_config(tmp_path)
    assert cfg.distill_provider == "claude"
    assert cfg.distill_base_url is None


# ---- distill.client 解決（client 本線 / provider alias / unconfigured） ----


def test_load_config_no_file_is_unconfigured(tmp_path: Path) -> None:
    """config.toml が無ければ distill は unconfigured"""
    cfg = load_config(tmp_path)
    assert cfg.distill_client is None
    assert cfg.distill_unconfigured is True


def test_load_config_explicit_client_ollama_ft(tmp_path: Path) -> None:
    """distill.client = "ollama-ft" はそのまま解決される"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        '[distill]\nclient = "ollama-ft"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_client == "ollama-ft"
    assert cfg.distill_unconfigured is False


def test_load_config_rejects_unapproved_remote_client(tmp_path: Path, capsys) -> None:
    """プロジェクト設定だけでリモート CLI へ会話を送信させない。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        '[distill]\nclient = "claude-cli"\n'
    )

    cfg = load_config(tmp_path)

    assert cfg.distill_client is None
    assert cfg.distill_unconfigured is True
    assert "LOCIACTION_REMOTE_DISTILL_CLIENTS" in capsys.readouterr().err

def test_load_config_allows_approved_remote_client(tmp_path: Path, monkeypatch) -> None:
    """ユーザー環境で明示許可した CLI client だけをプロジェクト設定から使う。"""
    monkeypatch.setenv("LOCIACTION_REMOTE_DISTILL_CLIENTS", "claude-cli")
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        '[distill]\nclient = "claude-cli"\n'
    )

    cfg = load_config(tmp_path)

    assert cfg.distill_client == "claude-cli"
    assert cfg.distill_unconfigured is False

def test_load_config_unknown_client_is_unconfigured(tmp_path: Path, capsys) -> None:
    """未知の client id は unconfigured として扱われ、暗黙解決しない"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        '[distill]\nclient = "bogus\\u001b]8;;https://evil.test\\u001b\\\\x"\n'
    )
    cfg = load_config(tmp_path)
    output = capsys.readouterr().err
    assert cfg.distill_client is None
    assert cfg.distill_unconfigured is True
    assert "unknown distill.client" in output
    assert "\x1b" not in output


def test_load_config_legacy_provider_claude_requires_remote_client_grant(
    tmp_path: Path, monkeypatch
) -> None:
    """旧 provider alias も remote CLI 許可を迂回できない。"""
    monkeypatch.setenv("LOCIACTION_REMOTE_DISTILL_CLIENTS", "claude-cli")
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text('[distill]\nprovider = "claude"\n')
    cfg = load_config(tmp_path)
    assert cfg.distill_client == "claude-cli"
    assert cfg.distill_unconfigured is False


def test_load_config_rejects_unapproved_legacy_remote_provider(
    tmp_path: Path,
) -> None:
    """legacy provider alias も user-environment grant なしには remote CLI を選べない。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text('[distill]\nprovider = "claude"\n')

    cfg = load_config(tmp_path)

    assert cfg.distill_client is None
    assert cfg.distill_unconfigured is True


def test_load_config_legacy_provider_openai_ollama_base_url_maps_to_ollama_ft(
    tmp_path: Path,
) -> None:
    """旧 provider = "openai" + Ollama base_url(11434) は client = "ollama-ft" として解決される"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        '[distill]\nprovider = "openai"\nbase_url = "http://localhost:11434/v1"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_client == "ollama-ft"
    assert cfg.distill_unconfigured is False


def test_load_config_legacy_provider_openai_other_base_url_maps_to_openai_compat(
    tmp_path: Path, monkeypatch
) -> None:
    """opt-in 済みの非 Ollama endpoint は openai-compat として解決される。"""
    monkeypatch.setenv(
        "LOCIACTION_REMOTE_DISTILL_ORIGINS", "https://api.deepseek.com"
    )
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        '[distill]\nprovider = "openai"\nbase_url = "https://api.deepseek.com"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_client == "openai-compat"
    assert cfg.distill_unconfigured is False


def test_load_config_rejects_explicit_remote_compat_client_without_opt_in(
    tmp_path: Path,
) -> None:
    """リモート config は explicit client でも distillation を設定済みにしない。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        '[distill]\nclient = "openai-compat"\nmodel = "remote-model"\n'
        'base_url = "https://api.example.test/v1"\n'
    )

    cfg = load_config(tmp_path)

    assert cfg.distill_base_url is None
    assert cfg.distill_client is None
    assert cfg.distill_unconfigured is True

def test_load_config_rejects_file_scheme_base_url(tmp_path: Path, capsys) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        '[distill]\nprovider = "openai"\nbase_url = "file:///etc/passwd"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_base_url is None
    assert cfg.distill_provider == DEFAULT_DISTILL_PROVIDER
    assert "Warning" in capsys.readouterr().err


def test_load_config_rejects_userinfo_base_url(tmp_path: Path) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        '[distill]\nprovider = "openai"\nbase_url = "https://user:pass@evil.example/v1"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_base_url is None
    assert cfg.distill_client != "openai-compat"


def test_load_config_neither_client_nor_provider_is_unconfigured(tmp_path: Path) -> None:
    """config.toml に [distill] があっても client/provider どちらも無ければ unconfigured"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        "[distill]\nbatch_limit = 5\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_client is None
    assert cfg.distill_unconfigured is True



# ---- #26: base_url 非 str の無言ドロップ / model デフォルト不整合 ----


def test_load_config_non_str_base_url_warns(tmp_path: Path, capsys) -> None:
    """base_url が非 str の場合、他フィールドと同様に警告を出して無視する
    （#26: 以前は無言で None にドロップしていた）"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        "[distill]\nbase_url = 123\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_base_url is None
    assert "Warning" in capsys.readouterr().err


def test_load_config_client_ollama_ft_missing_model_defers_to_none(
    tmp_path: Path,
) -> None:
    """client = "ollama-ft" で model 未設定なら claude デフォルトを使わず None のまま
    保持する（#26: 以前は DEFAULT_DISTILL_MODEL="claude-haiku-4-5..." を誤って
    採用し、Ollama に claude 用モデル名を送っていた）"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text('[distill]\nclient = "ollama-ft"\n')
    cfg = load_config(tmp_path)
    assert cfg.distill_client == "ollama-ft"
    assert cfg.distill_model is None
    assert cfg.distill_model != DEFAULT_DISTILL_MODEL


def test_load_config_client_ollama_ft_explicit_model_kept(tmp_path: Path) -> None:
    """client = "ollama-ft" で model が明示されていればそれを使う"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        '[distill]\nclient = "ollama-ft"\nmodel = "custom-ft:latest"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_model == "custom-ft:latest"


def test_load_config_client_claude_cli_missing_model_uses_claude_default(
    tmp_path: Path,
) -> None:
    """client = "claude-cli" で model 未設定なら claude デフォルトを使う
    （claude 向け client は claude 専用デフォルトが正しい）"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text('[distill]\nclient = "claude-cli"\n')
    cfg = load_config(tmp_path)
    assert cfg.distill_model == DEFAULT_DISTILL_MODEL


def test_load_config_legacy_provider_openai_ollama_missing_model_defers_to_none(
    tmp_path: Path,
) -> None:
    """旧 provider = "openai" + Ollama base_url + model 未設定でも、claude デフォルト
    に落ちずに None のまま保持する（registry 側の ollama-ft デフォルトへ委ねる）"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        "[distill]\nprovider = 'openai'\nbase_url = 'http://localhost:11434/v1'\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_client == "ollama-ft"
    assert cfg.distill_model is None


def test_load_config_legacy_provider_openai_compat_missing_model_defers_to_none(
    tmp_path: Path, monkeypatch
) -> None:
    """opt-in 済みの remote compat endpoint は model を勝手に補完しない。"""
    monkeypatch.setenv(
        "LOCIACTION_REMOTE_DISTILL_ORIGINS", "https://api.deepseek.com"
    )
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        "[distill]\nprovider = 'openai'\nbase_url = 'https://api.deepseek.com'\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.distill_client == "openai-compat"
    assert cfg.distill_model is None


def test_load_config_end_to_end_ollama_ft_resolves_to_local_distill_model(
    tmp_path: Path,
) -> None:
    """end-to-end: client="ollama-ft" + model 未設定 → resolve_client が
    LOCAL_DISTILL_MODEL を使う（claude-haiku-4-5 のような claude 専用モデル名を
    Ollama に送らない）"""
    from lociaction.adapters.model.registry import resolve_client

    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text('[distill]\nclient = "ollama-ft"\n')
    cfg = load_config(tmp_path)
    client = resolve_client("ollama-ft", cfg)
    assert client.model == LOCAL_DISTILL_MODEL
    assert client.model != DEFAULT_DISTILL_MODEL


def test_load_config_end_to_end_openai_compat_missing_model_raises(
    tmp_path: Path, monkeypatch
) -> None:
    """opt-in 済み remote compat はモデル未設定を明示エラーにする。"""
    from lociaction.adapters.model.registry import resolve_client

    monkeypatch.setenv(
        "LOCIACTION_REMOTE_DISTILL_ORIGINS", "https://api.deepseek.com"
    )
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "config.toml").write_text(
        "[distill]\nprovider = 'openai'\nbase_url = 'https://api.deepseek.com'\n"
    )
    cfg = load_config(tmp_path)
    try:
        resolve_client("openai-compat", cfg)
        raised = False
    except ValueError:
        raised = True
    assert raised