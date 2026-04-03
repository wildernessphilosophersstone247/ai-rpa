from __future__ import annotations

import pytest

from agent_android.transport import _should_bypass_proxy


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://localhost:8080", True),
        ("http://127.0.0.1:8080", True),
        ("http://192.168.3.20:8080", True),
        ("http://10.0.0.25:8080", True),
        ("http://device.local:8080", True),
        ("http://example.com", False),
        ("http://8.8.8.8:8080", False),
    ],
)
def test_should_bypass_proxy_matches_network_expectations(base_url, expected):
    assert _should_bypass_proxy(base_url) is expected
