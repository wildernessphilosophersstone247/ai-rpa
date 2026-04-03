from __future__ import annotations

import io
import sys

from agent_android.formatting import print_tree


def test_print_tree_replaces_unencodable_console_characters(monkeypatch):
    byte_buffer = io.BytesIO()
    stdout = io.TextIOWrapper(byte_buffer, encoding="gbk", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)

    print_tree(
        [
            {
                "refId": 1,
                "text": "codex•smoke",
                "simpleClassName": "TextView",
                "x": 1,
                "y": 2,
            }
        ]
    )
    stdout.flush()

    rendered = byte_buffer.getvalue().decode("gbk")
    assert "codex?smoke" in rendered
