from __future__ import annotations

import json

import pytest

from agent_android import config


def test_load_saved_url_returns_stripped_value(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-android.json"
    monkeypatch.setattr(config, "CONFIG_FILE_PATH", config_path)
    config_path.write_text(json.dumps({"url": " http://device:8080/ "}), encoding="utf-8")

    assert config.load_saved_url() == "http://device:8080/"


def test_save_url_to_config_writes_json_payload(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-android.json"
    monkeypatch.setattr(config, "CONFIG_FILE_PATH", config_path)

    config.save_url_to_config("  http://device:8080  ")

    assert json.loads(config_path.read_text(encoding="utf-8")) == {"url": "http://device:8080"}


def test_resolve_base_url_prefers_command_line_over_saved_value(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-android.json"
    monkeypatch.setattr(config, "CONFIG_FILE_PATH", config_path)
    config_path.write_text(json.dumps({"url": "http://saved:8080"}), encoding="utf-8")

    assert config.resolve_base_url("http://cli:8080") == "http://cli:8080"


def test_load_saved_url_returns_none_for_invalid_json(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-android.json"
    monkeypatch.setattr(config, "CONFIG_FILE_PATH", config_path)
    config_path.write_text("{invalid json", encoding="utf-8")

    assert config.load_saved_url() is None


def test_require_base_url_exits_when_no_value_available(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "agent-android.json"
    monkeypatch.setattr(config, "CONFIG_FILE_PATH", config_path)

    with pytest.raises(SystemExit) as exc_info:
        config.require_base_url(None)

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "AIVane server URL is required" in captured.err
