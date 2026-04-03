from __future__ import annotations

import base64

import pytest

from agent_android import client as client_module


class _UnexpectedNetworkOpener:
    def open(self, *_args, **_kwargs):
        raise AssertionError("Unexpected network access in unit test")


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(client_module, "_build_http_opener", lambda _base_url: _UnexpectedNetworkOpener())
    return client_module.AgentAndroidClient("http://device:8080")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"success": True, "apps": {"label": "Calculator", "package": "pkg.calc"}},
            [{"label": "Calculator", "package": "pkg.calc"}],
        ),
        (
            {"success": True, "data": {"apps": [{"label": "Maps", "package": "pkg.maps"}]}},
            [{"label": "Maps", "package": "pkg.maps"}],
        ),
        (
            {"success": True, "data": {"appList": [{"label": "Camera", "package": "pkg.camera"}]}},
            [{"label": "Camera", "package": "pkg.camera"}],
        ),
        (
            {"success": True, "data": [{"label": "Clock", "package": "pkg.clock"}]},
            [{"label": "Clock", "package": "pkg.clock"}],
        ),
    ],
)
def test_list_launcher_apps_normalizes_compatible_shapes(client, monkeypatch, payload, expected):
    monkeypatch.setattr(client, "_get_raw", lambda _path: payload)

    assert client.list_launcher_apps() == expected


def test_list_launcher_apps_returns_none_on_explicit_failure(client, monkeypatch):
    monkeypatch.setattr(client, "_get_raw", lambda _path: {"success": False})

    assert client.list_launcher_apps() is None


def test_get_health_returns_payload_dict(client, monkeypatch):
    payload = {"service": "aivane-repl", "status": "running"}
    monkeypatch.setattr(client, "_get_raw", lambda _path: payload)

    assert client.get_health() == payload


def test_get_ui_elements_caches_results_and_saves_snapshot(client, monkeypatch):
    elements = [{"refId": 1, "text": "Search"}]
    calls = {"fetch": 0, "save": 0}

    def fake_fetch():
        calls["fetch"] += 1
        return elements

    def fake_save(base_url, package_name, saved_elements):
        calls["save"] += 1
        assert base_url == "http://device:8080"
        assert package_name == "pkg.example"
        assert saved_elements == elements

    monkeypatch.setattr(client, "_fetch_ui_elements_impl", fake_fetch)
    monkeypatch.setattr(client, "get_current_package_name", lambda: "pkg.example")
    monkeypatch.setattr(client_module, "save_snapshot", fake_save)

    first = client.get_ui_elements()
    second = client.get_ui_elements()

    assert first == elements
    assert second == elements
    assert calls == {"fetch": 1, "save": 1}
    assert client._snapshot == {
        "baseUrl": "http://device:8080",
        "packageName": "pkg.example",
        "elements": elements,
    }


def test_resolve_action_target_rejects_snapshot_from_other_package(client, monkeypatch, capsys):
    client._snapshot = {
        "baseUrl": "http://device:8080",
        "packageName": "pkg.old",
        "elements": [{"refId": 7, "text": "Search"}],
    }
    monkeypatch.setattr(client, "get_current_package_name", lambda: "pkg.new")
    monkeypatch.setattr(
        client,
        "get_ui_elements",
        lambda *args, **kwargs: pytest.fail("get_ui_elements should not run for mismatched packages"),
    )

    assert client._resolve_action_target(7) is None
    assert "snapshot package=pkg.old, current package=pkg.new" in capsys.readouterr().err


def test_resolve_action_target_prefers_matching_element_from_current_tree(client, monkeypatch):
    snapshot_elem = {
        "refId": 7,
        "resourceId": "pkg:id/search",
        "text": "Search",
        "contentDesc": "",
        "simpleClassName": "EditText",
        "xpath": "//EditText[1]",
    }
    current_elem = {
        "refId": 99,
        "resourceId": "pkg:id/search",
        "text": "Search",
        "contentDesc": "",
        "simpleClassName": "EditText",
        "xpath": "//EditText[1]",
    }
    client._snapshot = {
        "baseUrl": "http://device:8080",
        "packageName": "pkg.example",
        "elements": [snapshot_elem],
    }
    monkeypatch.setattr(client, "get_current_package_name", lambda: "pkg.example")
    monkeypatch.setattr(client, "get_ui_elements", lambda *args, **kwargs: [current_elem])

    assert client._resolve_action_target(7) == current_elem


def test_wait_for_element_retries_until_text_match_is_found(client, monkeypatch):
    responses = [
        [],
        [{"refId": 2, "text": "Search", "contentDesc": "", "simpleClassName": "EditText"}],
    ]
    clock = _FakeClock()

    def fake_get_ui_elements(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(client, "get_ui_elements", fake_get_ui_elements)
    monkeypatch.setattr(client_module.time, "time", clock.time)
    monkeypatch.setattr(client_module.time, "sleep", clock.sleep)

    found = client.wait_for_element(text="search", timeout=2, interval=0.5)

    assert found is not None
    assert found["refId"] == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, 1),
        (False, 0),
        (5, 5),
        (3.9, 3),
        (" 7 ", 7),
        ("not-a-number", -1),
        (None, -1),
    ],
)
def test_parse_match_count_handles_common_runtime_shapes(client, value, expected):
    assert client._parse_match_count(value) == expected


def test_screenshot_writes_output_file_from_base64_payload(client, monkeypatch, tmp_path):
    image_bytes = b"fake-image-bytes"
    monkeypatch.setattr(
        client,
        "_get_raw",
        lambda _path, _params=None: {"success": True, "base64": base64.b64encode(image_bytes).decode("ascii")},
    )

    output_path = tmp_path / "smoke.jpg"
    saved_path = client.screenshot(output_path=str(output_path))

    assert saved_path == str(output_path)
    assert output_path.read_bytes() == image_bytes
