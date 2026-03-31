from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_FILE_PATH = Path(os.path.expanduser("~/.agent-android.json"))
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
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {}


def load_saved_url() -> Optional[str]:
    config = _load_saved_config()
    url = config.get(CONFIG_URL_KEY)
    if isinstance(url, str):
        stripped = url.strip()
        if stripped:
            return stripped
    return None


def save_url_to_config(url: str) -> None:
    CONFIG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {CONFIG_URL_KEY: url.strip()}
    CONFIG_FILE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_base_url(cmdline_url: Optional[str]) -> Optional[str]:
    if cmdline_url:
        trimmed = cmdline_url.strip()
        if trimmed:
            return trimmed
    return load_saved_url()


def require_base_url(cmdline_url: Optional[str]) -> str:
    url = resolve_base_url(cmdline_url)
    if url:
        return url
    print(
        "AIVane server URL is required. Provide it via `--url` or run "
        "`python agent-android.py --repl` and `set url <url>` to persist it under "
        f"{CONFIG_FILE_PATH}.",
        file=sys.stderr,
    )
    sys.exit(2)
