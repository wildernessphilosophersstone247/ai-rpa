from __future__ import annotations

import json

from agent_android import snapshot


def test_save_and_load_snapshot_round_trip(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "agent-android-snapshot.json"
    monkeypatch.setattr(snapshot, "SNAPSHOT_FILE_PATH", snapshot_path)
    elements = [{"refId": 7, "text": "Search"}]

    snapshot.save_snapshot("http://device:8080", "pkg.example", elements)
    loaded = snapshot.load_snapshot("http://device:8080")

    assert loaded is not None
    assert loaded["baseUrl"] == "http://device:8080"
    assert loaded["packageName"] == "pkg.example"
    assert loaded["elements"] == elements
    assert snapshot.find_snapshot_element(loaded, 7) == elements[0]


def test_load_snapshot_rejects_different_base_url(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "agent-android-snapshot.json"
    monkeypatch.setattr(snapshot, "SNAPSHOT_FILE_PATH", snapshot_path)
    snapshot_path.write_text(
        json.dumps(
            {
                "baseUrl": "http://other-device:8080",
                "packageName": "pkg.example",
                "elements": [{"refId": 1}],
            }
        ),
        encoding="utf-8",
    )

    assert snapshot.load_snapshot("http://device:8080") is None


def test_load_snapshot_returns_none_for_invalid_json(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "agent-android-snapshot.json"
    monkeypatch.setattr(snapshot, "SNAPSHOT_FILE_PATH", snapshot_path)
    snapshot_path.write_text("{broken json", encoding="utf-8")

    assert snapshot.load_snapshot("http://device:8080") is None
