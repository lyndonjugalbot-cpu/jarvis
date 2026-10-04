from pathlib import Path

from config import load_settings


def test_reads_config_and_env(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    monkeypatch.delenv("JARVIS_TOKEN", raising=False)
    config = tmp_path / "config.toml"
    config.write_text(
        '[core]\ndata_dir = "~/somewhere"\n'
        '[user]\nname = "Ada"\n'
        '[providers.claude_plan]\nmodel = "sonnet"\nbuiltin_tools = []\n'
    )
    env = tmp_path / ".env"
    env.write_text("JARVIS_TOKEN=abc\n")
    s = load_settings(config, env)
    assert s.data_dir == Path.home() / "somewhere"
    assert s.notes_dir == Path.home() / "somewhere" / "notes"
    assert (s.user_name, s.token, s.port) == ("Ada", "abc", 8765)
    assert (s.claude_plan.model, s.claude_plan.builtin_tools) == ("sonnet", ())


def test_defaults_without_files(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    s = load_settings(tmp_path / "missing.toml", tmp_path / "missing.env")
    assert s.data_dir == tmp_path
    assert s.provider_order == ("claude_plan",)
    assert s.user_name == "the user"
