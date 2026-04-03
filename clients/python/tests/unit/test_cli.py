from __future__ import annotations

import json
import sys

import pytest

from agent_android import cli as cli_module


def test_main_apps_command_exits_zero_and_prints_app_list(monkeypatch, capsys):
    class FakeClient:
        def __init__(self, url):
            self.base_url = url

        def list_launcher_apps(self):
            return [{"label": "Calculator", "package": "pkg.calc", "activity": "MainActivity"}]

    monkeypatch.setattr(cli_module, "AgentAndroidClient", FakeClient)
    monkeypatch.setattr(sys, "argv", ["agent-android.py", "--url", "http://device:8080", "--apps"])

    with pytest.raises(SystemExit) as exc_info:
        cli_module.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "Launcher apps:" in captured.out
    assert "Calculator - pkg.calc [MainActivity]" in captured.out


def test_main_health_command_exits_zero_and_prints_payload(monkeypatch, capsys):
    class FakeClient:
        def __init__(self, url):
            self.base_url = url

        def get_health(self):
            return {"service": "aivane-repl", "status": "running"}

    monkeypatch.setattr(cli_module, "AgentAndroidClient", FakeClient)
    monkeypatch.setattr(sys, "argv", ["agent-android.py", "--url", "http://device:8080", "--health"])

    with pytest.raises(SystemExit) as exc_info:
        cli_module.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert json.loads(captured.out) == {"service": "aivane-repl", "status": "running"}


def test_main_list_raw_writes_output_file(monkeypatch, tmp_path, capsys):
    elements = [{"refId": 1, "text": "Search"}]

    class FakeClient:
        def __init__(self, url):
            self.base_url = url

        def get_ui_elements(self, wait=0, force_refresh=False):
            assert wait == 0
            assert force_refresh is False
            return elements

    output_path = tmp_path / "tree.json"
    monkeypatch.setattr(cli_module, "AgentAndroidClient", FakeClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-android.py",
            "--url",
            "http://device:8080",
            "--list",
            "--raw",
            "--output",
            str(output_path),
        ],
    )

    assert cli_module.main() == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == elements
    assert json.loads(output_path.read_text(encoding="utf-8")) == elements
    assert "ARIA tree saved to:" in captured.err


def test_main_wait_for_command_reports_match(monkeypatch, capsys):
    class FakeClient:
        def __init__(self, url):
            self.base_url = url

        def wait_for_element(self, text=None, timeout=30):
            assert text == "Search"
            assert timeout == 12
            return {"refId": 8, "text": "Search", "simpleClassName": "TextView", "x": 10, "y": 20}

    monkeypatch.setattr(cli_module, "AgentAndroidClient", FakeClient)
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-android.py", "--url", "http://device:8080", "--wait-for", "Search", "--timeout", "12"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli_module.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "Waiting for element 'Search' (timeout=12s)" in captured.err
    assert "refId=8 found: text='Search' class=TextView at (10, 20)" in captured.out
