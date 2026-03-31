#!/usr/bin/env python3
"""
Minimal public helper for sending a template JSON to the Android REPL `/api/execute` endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


CONFIG_FILE_PATH = Path(os.path.expanduser("~/.aria_tree_config.json"))
CONFIG_URL_KEY = "url"


def _load_saved_config() -> Dict[str, Any]:
    if not CONFIG_FILE_PATH.exists():
        return {}
    try:
        raw = CONFIG_FILE_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_base_url(cmdline_url: Optional[str]) -> Optional[str]:
    if cmdline_url and cmdline_url.strip():
        return cmdline_url.strip()
    saved = _load_saved_config().get(CONFIG_URL_KEY)
    if isinstance(saved, str) and saved.strip():
        return saved.strip()
    return None


def require_base_url(cmdline_url: Optional[str]) -> str:
    url = resolve_base_url(cmdline_url)
    if url:
        return url
    print(
        f"Android API base URL is required. Provide --url or save it in {CONFIG_FILE_PATH}.",
        file=sys.stderr,
    )
    sys.exit(2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a template JSON via the Android REPL /api/execute endpoint.")
    parser.add_argument("template", help="Path to a template JSON file.")
    parser.add_argument("--url", default=None, help=f"Android API base URL. Overrides saved config at {CONFIG_FILE_PATH}")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds.")
    return parser.parse_args()


def load_template(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Template file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Template JSON is invalid: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    args = parse_args()
    url = require_base_url(args.url).rstrip("/")
    template_path = Path(args.template).expanduser().resolve()
    payload = load_template(template_path)

    request = urllib.request.Request(
        url + "/api/execute",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    print(body)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return 0
    return 0 if parsed.get("success") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
