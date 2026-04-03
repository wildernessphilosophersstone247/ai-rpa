from __future__ import annotations

import json

import pytest

from agent_android import repl as repl_module


class _DummyClient:
    def __init__(self, url):
        self.base_url = url
        self._local_tree = None

    def get_ui_elements(self, force_refresh=False):
        return []

    def get_current_package_name(self):
        return "pkg.example"

    def get_health(self):
        return {"service": "aivane-repl", "status": "running"}


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(repl_module, "AgentAndroidClient", _DummyClient)
    return repl_module.AriaReplSession(url="http://device:8080")


def test_parse_line_keeps_xpath_remainder_intact(session):
    command, args = session._parse_line("tx //node[@text='Hello world']")

    assert command == "tx"
    assert args == ["//node[@text='Hello world']"]


def test_parse_line_supports_inputx_delimiter_for_text_with_spaces(session):
    command, args = session._parse_line("ix //node[@resource-id='pkg:id/search'] -- hello world")

    assert command == "ix"
    assert args == ["//node[@resource-id='pkg:id/search']", "hello world"]


def test_parse_line_uses_shell_style_splitting_for_regular_commands(session):
    command, args = session._parse_line("set timeout 45")

    assert command == "set"
    assert args == ["timeout", "45"]


def test_execute_line_reports_unknown_command(session, capsys):
    assert session._execute_line("unknown-command") is False

    assert "Unknown command" in capsys.readouterr().err


def test_cmd_set_url_replaces_client_and_persists_value(session, monkeypatch, capsys):
    saved_urls = []
    monkeypatch.setattr(repl_module, "save_url_to_config", lambda url: saved_urls.append(url))

    assert session._cmd_set(["url", " http://new-device:8080 "]) is True

    captured = capsys.readouterr()
    assert session.client.base_url == "http://new-device:8080"
    assert saved_urls == ["http://new-device:8080"]
    assert "URL set to: http://new-device:8080" in captured.out


def test_cmd_set_timeout_updates_session_timeout(session, capsys):
    assert session._cmd_set(["timeout", "45"]) is True

    captured = capsys.readouterr()
    assert session._timeout == 45
    assert "Timeout set to: 45s" in captured.out


def test_cmd_set_rejects_empty_url(session, capsys):
    assert session._cmd_set(["url", "   "]) is False

    assert "URL cannot be empty" in capsys.readouterr().err


def test_cmd_health_prints_health_payload(session, capsys):
    assert session._cmd_health([]) is True

    captured = capsys.readouterr()
    assert "Health:" in captured.out
    assert "service: aivane-repl" in captured.out
    assert "status: running" in captured.out


def test_cmd_health_respects_raw_output(session, capsys):
    session._raw_output = True

    assert session._cmd_health([]) is True

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"service": "aivane-repl", "status": "running"}
