#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIVane Android REPL CLI helper for agent-android.

Cross-platform command line client for Linux, macOS, and Windows.

Usage:
    python agent-android.py --repl            # Enter the interactive REPL (recommended)
    python agent-android.py --list            # Run a one-off command (compatibility mode)

REPL quick reference:
    l [n]         List elements (first n entries, reuse cache)
    ss            Refresh the UI tree snapshot (force refresh)
    t <N>         Tap element with refId=N
    tx <xpath>    Tap by XPath locator (runtime evaluation)
    i <N> <text>  Enter text into refId=N
    ix <xpath> <text> Enter text via XPath locator
    vx <xpath>    Validate XPath match count in runtime layout
    sw <d>        Swipe direction (d/u/l/r, supports --dur/--dist)
    wf <text>     Wait for element text (use --t to override timeout)
    g <N> <attr>  Inspect attribute value for refId=N
    s [path]      Capture screenshot
    la <pkg>      Launch an app by package name
    b            Navigate back
    p <key>       Press a system key (back/home)
    ref <N>      Dump element details
    x <N>        Print XPath for refId=N
    f <text>     Filter tree elements by visible text
    id <resourceId> Filter elements by resourceId
    h            Show help
    q            Quit the REPL
    vars         Show session variables
    set url <u>  Switch the server URL
    set timeout <N> Adjust the default timeout
"""

import json
import sys
import os
import argparse
import ipaddress
import time
import re
import base64
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
import urllib.parse
import shlex
import traceback
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
try:
    import readline
    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False

if sys.platform == 'win32':
    import io
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


_REPL_EXIT = object()

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


def _should_bypass_proxy(base_url: str) -> bool:
    hostname = urllib.parse.urlparse(base_url).hostname
    if not hostname:
        return False
    if hostname == 'localhost':
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return hostname.endswith('.local')
    return address.is_private or address.is_loopback or address.is_link_local


def _build_http_opener(base_url: str) -> urllib.request.OpenerDirector:
    if _should_bypass_proxy(base_url):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _first_text(app: Dict[str, Any], keys: Tuple[str, ...], default: str = "") -> str:
    for key in keys:
        value = app.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _format_launcher_app(app: Dict[str, Any]) -> str:
    label = _first_text(app, ("label", "name", "appName", "title"), "<unnamed>")
    package = _first_text(app, ("package", "packageName", "pkg"), "<unknown>")
    activity = _first_text(app, ("activity", "launcherActivity", "mainActivity"), "-")
    extras = []
    if app.get("launcher", True) is False:
        extras.append("launcher=false")
    enabled = app.get("enabled")
    if isinstance(enabled, bool):
        extras.append("enabled" if enabled else "disabled")
    extra_text = f" ({', '.join(extras)})" if extras else ""
    return f"{label} — {package}{extra_text} [{activity}]"


class AgentAndroidClient:
    """Client for the AIVane Android REPL public API."""

    def __init__(self, base_url: str):
        trimmed = base_url.strip()
        if not trimmed:
            raise ValueError("Base URL is required")
        self.base_url = trimmed.rstrip('/')
        self.execute_url = f"{self.base_url}/api/execute"
        self._opener = _build_http_opener(self.base_url)
        self._local_tree: Optional[List[Dict]] = None  # In-process UI tree cache
        self._ui_tree_xml_cache: Optional[str] = None
        self._package_name_cache: Optional[str] = None

    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------

    def _api_call(self, template: Dict) -> Optional[Dict]:
        """发送 API 请求"""
        try:
            data = json.dumps(template, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(
                self.execute_url,
                data=data,
                headers={
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                method='POST'
            )
            with self._opener.open(req, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.URLError as e:
            print(f"Connection error: {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return None

    def _get_raw(self, path: str, params: Dict = None) -> Optional[Dict]:
        """GET 请求（用于 /health /screenshot /download 等端点）"""
        url = self.base_url + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'Accept': 'application/json',
                    'User-Agent': 'agent-android.py/0.1'
                }
            )
            with self._opener.open(req, timeout=30) as response:
                content = response.read()
                return json.loads(content.decode('utf-8'))
        except Exception as e:
            print(f"GET {url} error: {e}", file=sys.stderr)
            return None

    def list_launcher_apps(self) -> Optional[List[Dict[str, Any]]]:
        """Retrieve the launcher app list from /api/apps."""
        result = self._get_raw("/api/apps")
        if not result:
            return None
        if result.get('success') is False:
            return None
        apps = result.get('apps')
        if apps is None:
            data = result.get('data')
            if isinstance(data, dict):
                apps = data.get('apps') or data.get('appList')
            elif isinstance(data, list):
                apps = data
        if isinstance(apps, dict):
            apps = [apps]
        if not isinstance(apps, list):
            return []
        return [entry for entry in apps if isinstance(entry, dict)]

    def _download_binary(self, path: str, params: Dict = None) -> Optional[bytes]:
        """Download a binary payload from the Android runtime."""
        url = self.base_url + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        try:
            with self._opener.open(url, timeout=60) as response:
                return response.read()
        except Exception as e:
            print(f"Download error: {e}", file=sys.stderr)
            return None

    def _execute_single_operation(self, template_id: str, operation_type: str,
                                  parameters: Optional[Dict[str, Any]] = None
                                  ) -> Optional[Dict]:
        """Execute a single template operation."""
        return self._api_call({
            "templateId": template_id,
            "operations": [
                {"operationType": operation_type, "parameters": parameters or {}}
            ]
        })

    def _execute_template(self, template_id: str,
                          operations: List[Dict[str, Any]],
                          output_names: Optional[List[str]] = None
                          ) -> Optional[Dict]:
        """Run a multi-step template and optionally declare output variables."""
        template: Dict[str, Any] = {
            "templateId": template_id,
            "operations": operations,
        }
        if output_names:
            template["parameters"] = [
                {"name": name, "type": "STRING", "direction": "OUTPUT"}
                for name in output_names
            ]
        return self._api_call(template)

    def _get_outputs(self, result: Optional[Dict]) -> Dict[str, Any]:
        """Extract the outputs block from a successful /api/execute response."""
        if not result or not result.get('success'):
            return {}
        outputs = result.get('data', {}).get('outputs', {})
        return outputs if isinstance(outputs, dict) else {}

    def _run_single_operation(self, template_id: str, operation_type: str,
                              parameters: Optional[Dict[str, Any]],
                              success_message: str,
                              failure_prefix: str) -> bool:
        """Execute an operation and print a consistent success/failure message."""
        result = self._execute_single_operation(template_id, operation_type, parameters)
        if result and result.get('success'):
            print(success_message)
            self._local_tree = None
            self._ui_tree_xml_cache = None
            return True

        msg = result.get('errorMessage', 'Unknown error') if result else 'no response'
        print(f"{failure_prefix}: {msg}")
        return False

    def _get_coordinates(self, elem: Dict[str, Any], label: str
                         ) -> Optional[Tuple[Any, Any]]:
        """Retrieve tap coordinates, failing if none are provided."""
        x, y = elem.get('x'), elem.get('y')
        if x is None or y is None:
            print(f"{label} has no coordinates")
            return None
        return x, y

    def _parse_match_count(self, value: Any) -> int:
        """Convert a runtime match-count metadata value into an integer."""
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return -1
        return -1

    def _get_xpath_match_count(self, xpath: str) -> Optional[int]:
        """使用 Android 运行时 evaluator 统计 XPath 匹配数量。"""
        result = self._execute_template(
            template_id="xpath-validate-count",
            output_names=["matchCount"],
            operations=[
                {
                    "operationType": "android.element.getAll",
                    "parameters": {
                        "xpath": xpath,
                        "variableName": "matches",
                    }
                },
                {
                    "operationType": "list.process",
                    "parameters": {
                        "operation": "size",
                        "list": "${matches}",
                        "output": "matchCount",
                    }
                }
            ]
        )
        if not result:
            return None
        if not result.get('success'):
            return None
        outputs = self._get_outputs(result)
        if "matchCount" not in outputs:
            return None
        return self._parse_match_count(outputs.get("matchCount"))

    def _describe_unique_xpath_match(self, xpath: str) -> Dict[str, Any]:
        """当 XPath 唯一匹配时，读取首个元素的几个关键属性。"""
        result = self._execute_template(
            template_id="xpath-describe-unique",
            output_names=["textValue", "contentDescriptionValue", "classNameValue", "boundsValue"],
            operations=[
                {
                    "operationType": "android.element.getAttribute",
                    "parameters": {
                        "xpath": xpath,
                        "attribute": "text",
                        "targetVariable": "textValue",
                        "optional": True,
                    }
                },
                {
                    "operationType": "android.element.getAttribute",
                    "parameters": {
                        "xpath": xpath,
                        "attribute": "content-desc",
                        "targetVariable": "contentDescriptionValue",
                        "optional": True,
                    }
                },
                {
                    "operationType": "android.element.getAttribute",
                    "parameters": {
                        "xpath": xpath,
                        "attribute": "className",
                        "targetVariable": "classNameValue",
                        "optional": True,
                    }
                },
                {
                    "operationType": "android.element.getAttribute",
                    "parameters": {
                        "xpath": xpath,
                        "attribute": "bounds",
                        "targetVariable": "boundsValue",
                        "optional": True,
                    }
                }
            ]
        )
        outputs = self._get_outputs(result)
        return {
            "text": outputs.get("textValue"),
            "contentDescription": outputs.get("contentDescriptionValue"),
            "className": outputs.get("classNameValue"),
            "bounds": outputs.get("boundsValue"),
        }

    def validate_xpath_runtime(self, xpath: str) -> Optional[Dict[str, Any]]:
        """用 Android 运行时 evaluator 校验 XPath，并在唯一匹配时返回摘要。"""
        count = self._get_xpath_match_count(xpath)
        if count is None:
            return None

        info: Dict[str, Any] = {
            "xpath": xpath,
            "count": count,
        }
        if count == 1:
            info.update(self._describe_unique_xpath_match(xpath))
        return info

    def get_ui_tree_xml(self, force_refresh: bool = False) -> Optional[str]:
        """获取完整无障碍 UI tree XML。"""
        if not force_refresh and self._ui_tree_xml_cache is not None:
            return self._ui_tree_xml_cache

        result = self._execute_template(
            template_id="ui-tree-dump-inline",
            output_names=["uiTreeContent"],
            operations=[
                {
                    "operationType": "android.ui.dumpTree",
                    "parameters": {
                        "filePath": "/storage/emulated/0/Android/data/aivane.apprepl/files/ui_tree_dump.xml",
                        "format": "xml",
                        "variableName": "uiTreeContent",
                    },
                }
            ],
        )
        outputs = self._get_outputs(result)
        xml_text = outputs.get("uiTreeContent")
        if isinstance(xml_text, str) and xml_text.strip():
            self._ui_tree_xml_cache = xml_text
            return xml_text
        return None

    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------

    def get_ui_elements(self, wait: int = 0, force_refresh: bool = False
                        ) -> Optional[List[Dict]]:
        """
        Fetch the current UI element list.

        Results are cached within this client instance unless
        `force_refresh=True`.
        """
        if wait > 0:
            time.sleep(wait)

        if not force_refresh and self._local_tree is not None:
            return self._local_tree

        elements = self._fetch_ui_elements_impl()
        if elements is not None:
            self._local_tree = elements
        return elements

    def _fetch_ui_elements_impl(self) -> Optional[List[Dict]]:
        """Fetch the UI element list from the API."""
        json_str = (
            '{"templateId":"ui-elements-get","templateName":"UI Elements Query",'
            '"parameters":[{"name":"uiElements","type":"STRING","direction":"OUTPUT"}],'
            '"operations":['
            '{"operationType":"android.ui.getAriaTree","parameters":{"variableName":"tree"}},'
            '{"operationType":"variable.assign","parameters":{"variableName":"uiElements","value":"\\u0024{tree}"}}'
            ']}'
        )
        result = self._api_call(json.loads(json_str))
        if not result:
            return None

        if not result.get('success'):
            print(f"Error: {result.get('errorMessage', 'Unknown error')}", file=sys.stderr)
            return None

        outputs = result.get('data', {}).get('outputs', {})
        if isinstance(outputs, dict):
            ui_elements_json = outputs.get('uiElements', '[]')
        else:
            ui_elements_json = '[]'

        try:
            elements = json.loads(ui_elements_json)
            return elements
        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}", file=sys.stderr)
            return None

    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------

    def wait_for_element(self, text: str = None, refId: int = None,
                         timeout: int = 30, interval: float = 1.0
                         ) -> Optional[Dict]:
        """
        轮询 ARIA 树直到找到目标元素或超时。
        返回找到的元素 Dict，找不到返回 None。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            elements = self.get_ui_elements(force_refresh=True)
            if elements:
                if refId is not None:
                    for e in elements:
                        if e.get('refId') == refId:
                            print(f"[wait-for] Found refId={refId} after {timeout - int(deadline - time.time())}s")
                            return e
                elif text is not None:
                    for e in elements:
                        t = e.get('text', '') or ''
                        d = e.get('contentDesc', '') or ''
                        if text.lower() in t.lower() or text.lower() in d.lower():
                            print(f"[wait-for] Found text='{e.get('text', '')}' (refId={e.get('refId')}) after {timeout - int(deadline - time.time())}s")
                            return e
            remaining = int(deadline - time.time())
            if remaining > 0:
                time.sleep(min(interval, remaining))
        print(f"[wait-for] Timeout after {timeout}s (text='{text}', refId={refId})", file=sys.stderr)
        return None

    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------

    def tap_element(self, refId: int) -> bool:
        """点击指定 refId 的元素（复用本地缓存的树）"""
        target = self._find_element_by_refId(refId)
        if not target:
            return False

        coords = self._get_coordinates(target, f"Element refId={refId}")
        if not coords:
            return False
        x, y = coords

        return self._run_single_operation(
            template_id=f"tap-refId-{refId}",
            operation_type="android.touch.tap",
            parameters={"mode": "coordinate", "x": x, "y": y},
            success_message=f"Tapped refId={refId} at ({x}, {y})",
            failure_prefix="Tap failed"
        )

    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------

    def input_to_element(self, refId: int, text: str, clearFirst: bool = True) -> bool:
        """向指定 refId 的元素输入文本（复用本地缓存的树）"""
        target = self._find_element_by_refId(refId)
        if not target:
            return False

        elem_desc = target.get('text') or target.get('contentDesc') or f"refId={refId}"
        coords = self._get_coordinates(target, f"Element refId={refId}")
        if not coords:
            return False
        x, y = coords

        print(f"Inputting '{text}' to '{elem_desc}' (refId={refId}) at ({x}, {y})")

        return self._run_single_operation(
            template_id=f"input-refId-{refId}",
            operation_type="android.element.input",
            parameters={
                "x": x,
                "y": y,
                "value": text,
                "clearFirst": clearFirst
            },
            success_message=f"SUCCESS: Input '{text}' to element refId={refId}",
            failure_prefix="FAILED"
        )

    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------

    def swipe(self, direction: str = "down", duration: int = 300,
              distance: float = 0.5) -> bool:
        """
        执行滑动手势。
        direction: up / down / left / right
        duration:  滑动持续时间（毫秒）
        distance:  滑动距离占屏幕比例（0.0-1.0）
        """
        d = direction.lower()
        if d not in ('up', 'down', 'left', 'right'):
            print(f"Invalid direction: {direction}, use: up/down/left/right")
            return False

        return self._run_single_operation(
            template_id=f"swipe-{d}",
            operation_type="android.touch.swipe",
            parameters={
                "type": "direction",
                "direction": d,
                "duration": duration,
                "distance": distance
            },
            success_message=f"Swiped {d} (duration={duration}ms, distance={distance})",
            failure_prefix="Swipe failed"
        )

    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------

    def screenshot(self, output_path: str = None,
                   quality: int = 80) -> Optional[str]:
        """
        执行截图并下载到本地。
        返回本地保存的文件路径，失败返回 None。
        """
        print(f"Capturing screenshot (quality={quality})...", file=sys.stderr)
        data = self._get_raw("/screenshot", {"quality": str(quality)})

        if not data:
            print("Screenshot: fallback to template-based capture", file=sys.stderr)
            return self._screenshot_via_template(output_path, quality)

        if not data.get('success'):
            print(f"Screenshot failed: {data.get('errorMessage', 'Unknown error')}", file=sys.stderr)
            return None

        base64_data = data.get('base64', '')
        if not base64_data:
            print("Screenshot: no base64 data in response", file=sys.stderr)
            return None

        image_bytes = base64.b64decode(base64_data)
        size_kb = len(image_bytes) // 1024

        if not output_path:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_path = f"screenshot_{timestamp}.jpg"

        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(output_path, 'wb') as f:
            f.write(image_bytes)

        print(f"Screenshot saved: {output_path} ({size_kb}KB)", file=sys.stderr)
        return output_path

    def _screenshot_via_template(self, output_path: str = None, quality: int = 80) -> Optional[str]:
        """降级方案：通过模板 API 截图，然后下载文件"""
        if not output_path:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_path = f"screenshot_{timestamp}.png"

        package = self._get_package_name()
        save_path = f"/data/data/{package}/files/aria_screenshot.png" if package else "/sdcard/aria_screenshot.png"
        fmt = "jpeg" if quality < 100 else "png"

        template = {
            "templateId": "screenshot-capture",
            "operations": [
                {"operationType": "android.screenshot.capture", "parameters": {
                    "savePath": save_path,
                    "format": fmt,
                    "quality": quality
                }}
            ]
        }
        result = self._api_call(template)
        if not result or not result.get('success'):
            msg = result.get('errorMessage', 'Unknown') if result else 'no response'
            print(f"Screenshot failed: {msg}", file=sys.stderr)
            return None

        file_data = self._download_binary("/download", {"path": save_path})
        if not file_data:
            print(f"Screenshot: file download failed (but API succeeded)", file=sys.stderr)
            return None

        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        with open(output_path, 'wb') as f:
            f.write(file_data)
        print(f"Screenshot saved: {output_path} ({len(file_data)//1024}KB)", file=sys.stderr)
        return output_path

    def _get_package_name(self) -> Optional[str]:
        """获取当前前台 App 包名"""
        template = {
            "templateId": "current-app",
            "operations": [
                {"operationType": "android.app.current", "parameters": {}}
            ]
        }
        result = self._api_call(template)
        if result and result.get('success'):
            data = result.get('data', {})
            return data.get('packageName')
        return None

    def _get_package_name_from_dump_tree(self) -> Optional[str]:
        """通过 dumpTree(json) 根节点获取当前前台包名。"""
        result = self._execute_template(
            template_id="ui-tree-package-probe",
            output_names=["uiTreeJson"],
            operations=[
                {
                    "operationType": "android.ui.dumpTree",
                    "parameters": {
                        "filePath": "/storage/emulated/0/Android/data/aivane.apprepl/files/ui_tree_dump.json",
                        "format": "json",
                        "variableName": "uiTreeJson",
                    },
                }
            ],
        )
        outputs = self._get_outputs(result)
        ui_tree_json = outputs.get("uiTreeJson")
        if not isinstance(ui_tree_json, str) or not ui_tree_json.strip():
            return None
        try:
            data = json.loads(ui_tree_json)
        except json.JSONDecodeError:
            return None
        package_name = data.get("packageName")
        return package_name if isinstance(package_name, str) and package_name.strip() else None

    def get_current_package_name(self) -> Optional[str]:
        """公开当前前台包名查询，供列表/诊断输出使用。"""
        package_name = self._get_package_name()
        if not package_name:
            package_name = self._get_package_name_from_dump_tree()
        if package_name:
            self._package_name_cache = package_name
            return package_name
        return self._package_name_cache

    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------

    def press_key(self, key: str) -> bool:
        """
        按下指定按键。
        key: back / home / menu / enter / delete
        """
        key_map = {
            "back": "android.press.back",
            "home": "android.press.home",
            "menu": "android.press.menu",
            "enter": "android.press.enter",
            "delete": "android.press.delete",
            "power": "android.press.power",
        }
        op_type = key_map.get(key.lower())
        if not op_type:
            print(f"Unknown key: {key}. Available: {', '.join(key_map.keys())}", file=sys.stderr)
            return False

        if op_type == "android.press.back":
            template = {"templateId": "press-back", "operations": [
                {"operationType": "android.press.back", "parameters": {}}]}
        elif op_type == "android.press.home":
            template = {"templateId": "press-home", "operations": [
                {"operationType": "android.press.home", "parameters": {}}]}
        else:
            print(f"Key '{key}' not yet supported, please use --back for back key", file=sys.stderr)
            return False

        result = self._api_call(template)
        if result and result.get('success'):
            print(f"Pressed: {key}")
            self._local_tree = None
            return True

        msg = result.get('errorMessage', 'Unknown') if result else 'no response'
        print(f"Press key failed: {msg}")
        return False

    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------

    def get_attribute(self, refId: int, attribute: str) -> Optional[str]:
        """
        获取 refId 对应元素的指定属性值。
        attribute: text / content-desc / className / resourceId / bounds 等
        """
        target = self._find_element_by_refId(refId)
        if not target:
            print(f"Element refId={refId} not found")
            return None

        attr_map = {
            "text": "text",
            "content-desc": "contentDesc",
            "contentdesc": "contentDesc",
            "desc": "contentDesc",
            "classname": "simpleClassName",
            "class": "simpleClassName",
            "classname": "simpleClassName",
            "resourceid": "resourceId",
            "id": "resourceId",
            "bounds": "bounds",
            "x": "x",
            "y": "y",
            "refid": "refId",
            "xpath": "xpath",
            "selector": "selector",
            "clickable": "clickable",
            "enabled": "enabled",
            "focusable": "focusable",
            "visible": "visible",
        }
        key = attr_map.get(attribute.lower())
        if not key:
            print(f"Unknown attribute: {attribute}")
            return None

        value = target.get(key, 'N/A')
        print(f"refId={refId} {attribute} = {value}")
        return str(value) if value is not None else None

    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------

    def launch_app(self, package: str) -> bool:
        return self._run_single_operation(
            template_id=f"launch-{package}",
            operation_type="android.app.launch",
            parameters={"packageName": package},
            success_message=f"Launched: {package}",
            failure_prefix="Launch failed"
        )

    def press_back(self) -> bool:
        return self._run_single_operation(
            template_id="back",
            operation_type="android.press.back",
            parameters={},
            success_message="Pressed back",
            failure_prefix="Back failed"
        )

    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------

    def _find_element_by_refId(self, refId: int,
                                force_refresh: bool = False) -> Optional[Dict]:
        """从缓存树中查找元素（找不到才重新获取）"""
        tree = self.get_ui_elements(force_refresh=force_refresh)
        if not tree:
            return None
        for elem in tree:
            if elem.get('refId') == refId:
                return elem
        print(f"Element with refId={refId} not found in tree ({len(tree)} elements)")
        return None

    def find_by_refId(self, elements: List[Dict], refId: int) -> Optional[Dict]:
        for elem in elements:
            if elem.get('refId') == refId:
                return elem
        return None

    def find_by_resourceId(self, elements: List[Dict], resourceId: str) -> List[Dict]:
        return [e for e in elements if e.get('resourceId') == resourceId]

    def find_by_text(self, elements: List[Dict], text: str) -> List[Dict]:
        return [e for e in elements if text.lower() in (e.get('text', '') or '').lower()]

    def find_input_elements(self, elements: List[Dict]) -> List[Dict]:
        return [e for e in elements if e.get('focusable') or e.get('editable') or
                e.get('simpleClassName') in ['EditText', 'TextView']]

    def find_by_xpath(self, elements: List[Dict], xpath: str) -> Optional[Dict]:
        """
        根据 XPath 条件查找元素。
        支持格式: //ClassName[@attr='value'][@attr2='value2']
              //ClassName[@following-sibling::OtherClass]
              //ClassName[@preceding-sibling::OtherClass]
        例如: //EditText[@text='搜索, ']
              //Button[@text='搜索'][following-sibling::Button]
              //TextView[@contentDesc='搜索'][clickable]
        返回第一个匹配元素，或 None。
        """
        import re
        attrs = {}

        attrs = {}
        i = 0
        while i < len(xpath):
            if xpath[i] == '[':
                j = i + 1
                depth = 1
                in_quote = None  # 当前是否在引号内，以及是什么引号
                while j < len(xpath) and depth > 0:
                    ch = xpath[j]
                    if in_quote is not None:
                        if ch == in_quote:
                            in_quote = None
                    else:
                        if ch == '[':
                            depth += 1
                        elif ch == ']':
                            depth -= 1
                        elif ch in ("'", '"'):
                            in_quote = ch
                    j += 1
                cond = xpath[i+1:j-1]
                if cond.startswith('@'):
                    eq_pos = cond.find('=')
                    if eq_pos > 0:
                        attr = cond[1:eq_pos].strip()
                        raw_value = cond[eq_pos+1:].strip()
                        if raw_value and raw_value[0] in ("'", '"'):
                            quote_char = raw_value[0]
                            end = 1
                            while end < len(raw_value):
                                if raw_value[end] == quote_char:
                                    num_backslash = 0
                                    j2 = end - 1
                                    while j2 >= 1 and raw_value[j2] == '\\':
                                        num_backslash += 1
                                        j2 -= 1
                                    if num_backslash % 2 == 0:  # 非转义引号
                                        break
                                end += 1
                            value = raw_value[1:end]  # 去掉首尾引号
                        else:
                            bracket_pos = raw_value.find(']')
                            value = raw_value[:bracket_pos].strip() if bracket_pos >= 0 else raw_value.strip()
                        if value:
                            attrs[attr] = value
                else:
                    # following-sibling::ClassName / preceding-sibling::ClassName
                    cond_stripped = cond.strip()
                    for axis in ('following-sibling::', 'preceding-sibling::'):
                        if cond_stripped.startswith(axis):
                            tag = cond_stripped[len(axis):].strip()
                            if tag:
                                attrs[f'_{axis.rstrip(":")}'] = tag
                            break
                    else:
                        cond = cond.strip()
                        if cond in ('clickable', 'focusable', 'long-clickable', 'scrollable'):
                            attrs[cond] = True
                        elif cond.isdigit():
                            attrs['_position'] = int(cond)
                i = j
            else:
                i += 1

        elem_refId: Dict[int, Dict] = {e.get('refId'): e for e in elements if e.get('refId') is not None}
        # seg_to_elem[(depth, seg)] = elem
        seg_to_elem: Dict[tuple, Dict] = {}
        for e in elements:
            rid = e.get('refId')
            if rid is None:
                continue
            xp = e.get('xpath', '')
            segs = [s for s in xp.split('/') if s and s != 'WindowRoot']
            for di, seg in enumerate(segs):
                depth = di + 1
                key = (depth, seg)
                if key not in seg_to_elem:
                    seg_to_elem[key] = []
                seg_to_elem[key].append(e)

        def _get_prefix_seg(xp: str, up_to_depth: int) -> str:
            """取 xpath 前 N 段的最小公共形式（去掉索引如 [2]）"""
            segs = [s for s in xp.split('/') if s and s != 'WindowRoot']
            parts = []
            for di in range(min(up_to_depth, len(segs))):
                seg = segs[di]
                idx = seg.find('[')
                cls = seg[:idx] if idx >= 0 else seg
                parts.append(cls)
            return '/'.join(parts)

        parent_of: Dict[int, int] = {}
        for e in elements:
            rid = e.get('refId')
            if rid is None:
                continue
            xp = e.get('xpath', '')
            segs = [s for s in xp.split('/') if s and s != 'WindowRoot']
            depth = len(segs)
            if depth < 2:
                parent_of[rid] = None
                continue
            parent_seg = segs[-2]  # 倒数第二个 segment = 父节点
            candidates = seg_to_elem.get((depth - 1, parent_seg), [])
            if len(candidates) == 1:
                parent_of[rid] = candidates[0].get('refId')
            elif len(candidates) > 1:
                best = None
                best_len = 0
                xp_prefix = '/'.join(segs[:-1])
                for c in candidates:
                    c_xp = c.get('xpath', '')
                    c_prefix = '/'.join(
                        s for s in c_xp.split('/')
                        if s and s != 'WindowRoot'
                    )
                    if c_prefix and xp_prefix.startswith(c_prefix) and len(c_prefix) > best_len:
                        best = c.get('refId')
                        best_len = len(c_prefix)
                parent_of[rid] = best
            else:
                parent_of[rid] = None

        parent_children2: Dict[int, List[int]] = {}
        for rid, pid in parent_of.items():
            if pid is not None:
                parent_children2.setdefault(pid, []).append(rid)

        elem_refId2: Dict[int, Dict] = {e.get('refId'): e for e in elements if e.get('refId') is not None}

        def matches(elem: Dict) -> bool:
            for k, v in attrs.items():
                if k == 'refId':
                    if str(elem.get('refId', '')) != v:
                        return False
                elif k == 'text':
                    if (elem.get('text', '') or '') != v:
                        return False
                elif k in ('contentDesc', 'contentDescription', 'content-desc', 'contentdesc'):
                    if v.lower() not in (elem.get('contentDesc', '') or '').lower():
                        return False
                elif k == 'resourceId':
                    if elem.get('resourceId', '') != v:
                        return False
                elif k == 'className' or k == 'class':
                    if v.lower() not in (elem.get('simpleClassName', '') or '').lower():
                        return False
                elif k == 'clickable':
                    if not elem.get('clickable'):
                        return False
                elif k == 'focusable':
                    if not elem.get('focusable'):
                        return False
                elif k in ('x', 'y'):
                    elem_coord = elem.get(k)
                    try:
                        target = int(v)
                    except (ValueError, TypeError):
                        target = v
                    if elem_coord != target:
                        return False
                elif k == '_position':
                    target_idx = v
                    cls = elem.get('simpleClassName', '')
                    if not cls:
                        return False
                    same_cls_all = [e for e in elements if e.get('simpleClassName') == cls]
                    try:
                        actual_idx = same_cls_all.index(elem) + 1
                        if actual_idx != target_idx:
                            return False
                    except ValueError:
                        return False
                elif k == '_following-sibling':
                    rid = elem.get('refId')
                    pid = parent_of.get(rid)
                    siblings = parent_children2.get(pid, []) if pid else []
                    try:
                        idx = siblings.index(rid)
                        siblings_after = siblings[idx + 1:]
                    except ValueError:
                        siblings_after = []
                    for sib_rid in siblings_after:
                        sib = elem_refId2.get(sib_rid)
                        if sib and sib.get('simpleClassName', '') == v:
                            return True
                    return False
                elif k == '_preceding-sibling':
                    rid = elem.get('refId')
                    pid = parent_of.get(rid)
                    siblings = parent_children2.get(pid, []) if pid else []
                    try:
                        idx = siblings.index(rid)
                        siblings_before = siblings[:idx]
                    except ValueError:
                        siblings_before = []
                    for sib_rid in reversed(siblings_before):
                        sib = elem_refId2.get(sib_rid)
                        if sib and sib.get('simpleClassName', '') == v:
                            return True
                    return False
            return True

        for elem in elements:
            if matches(elem):
                return elem
        return None

    def find_by_xpath_all(self, elements: List[Dict], xpath: str) -> List[Dict]:
        """
        根据 XPath 条件查找所有匹配元素。
        与 find_by_xpath 相同逻辑，但返回所有匹配项而非仅第一个。
        """
        import re
        attrs = {}

        i = 0
        while i < len(xpath):
            if xpath[i] == '[':
                j = i + 1
                depth = 1
                in_quote = None
                while j < len(xpath) and depth > 0:
                    ch = xpath[j]
                    if in_quote is not None:
                        if ch == in_quote:
                            in_quote = None
                    else:
                        if ch == '[':
                            depth += 1
                        elif ch == ']':
                            depth -= 1
                        elif ch in ("'", '"'):
                            in_quote = ch
                    j += 1
                cond = xpath[i+1:j-1]
                if cond.startswith('@'):
                    eq_pos = cond.find('=')
                    if eq_pos > 0:
                        attr = cond[1:eq_pos].strip()
                        raw_value = cond[eq_pos+1:].strip()
                        if raw_value and raw_value[0] in ("'", '"'):
                            quote_char = raw_value[0]
                            end = 1
                            while end < len(raw_value):
                                if raw_value[end] == quote_char:
                                    num_backslash = 0
                                    j2 = end - 1
                                    while j2 >= 1 and raw_value[j2] == '\\':
                                        num_backslash += 1
                                        j2 -= 1
                                    if num_backslash % 2 == 0:
                                        break
                                end += 1
                            value = raw_value[1:end]
                        else:
                            bracket_pos = raw_value.find(']')
                            value = raw_value[:bracket_pos].strip() if bracket_pos >= 0 else raw_value.strip()
                        if value:
                            attrs[attr] = value
                else:
                    cond_stripped = cond.strip()
                    for axis in ('following-sibling::', 'preceding-sibling::'):
                        if cond_stripped.startswith(axis):
                            tag = cond_stripped[len(axis):].strip()
                            if tag:
                                attrs[f'_{axis.rstrip(":")}'] = tag
                            break
                    else:
                        cond = cond.strip()
                        if cond in ('clickable', 'focusable', 'long-clickable', 'scrollable'):
                            attrs[cond] = True
                i = j
            else:
                i += 1

        elem_refId: Dict[int, Dict] = {e.get('refId'): e for e in elements if e.get('refId') is not None}
        nodes = self._build_tree_structure(elements)
        parent_children: Dict[int, List[int]] = {}
        for ref_id, node in nodes.items():
            pid = node.get('parent_ref_id')
            if pid is not None:
                parent_children.setdefault(pid, []).append(ref_id)

        def matches(elem: Dict) -> bool:
            for k, v in attrs.items():
                if k == 'refId':
                    if str(elem.get('refId', '')) != v:
                        return False
                elif k == 'text':
                    if (elem.get('text', '') or '') != v:
                        return False
                elif k in ('contentDesc', 'contentDescription', 'content-desc', 'contentdesc'):
                    if v.lower() not in (elem.get('contentDesc', '') or '').lower():
                        return False
                elif k == 'resourceId':
                    if elem.get('resourceId', '') != v:
                        return False
                elif k == 'className' or k == 'class':
                    if v.lower() not in (elem.get('simpleClassName', '') or '').lower():
                        return False
                elif k == 'clickable':
                    if not elem.get('clickable'):
                        return False
                elif k == 'focusable':
                    if not elem.get('focusable'):
                        return False
                elif k in ('x', 'y'):
                    elem_coord = elem.get(k)
                    try:
                        target = int(v)
                    except (ValueError, TypeError):
                        target = v
                    if elem_coord != target:
                        return False
                elif k == '_position':
                    target_idx = v
                    cls = elem.get('simpleClassName', '')
                    if not cls:
                        return False
                    same_cls_all = [e for e in elements if e.get('simpleClassName') == cls]
                    try:
                        actual_idx = same_cls_all.index(elem) + 1
                        if actual_idx != target_idx:
                            return False
                    except ValueError:
                        return False
                elif k == '_following-sibling':
                    rid = elem.get('refId')
                    pid = None
                    siblings_after = []
                    for p, kids in parent_children.items():
                        try:
                            idx = kids.index(rid)
                            pid = p
                            siblings_after = kids[idx + 1:]
                            break
                        except ValueError:
                            continue
                    if pid is None:
                        return False
                    for sib_rid in siblings_after:
                        sib = elem_refId.get(sib_rid)
                        if sib and sib.get('simpleClassName', '') == v:
                            return True
                    return False
                elif k == '_preceding-sibling':
                    rid = elem.get('refId')
                    pid = None
                    siblings_before = []
                    for p, kids in parent_children.items():
                        try:
                            idx = kids.index(rid)
                            pid = p
                            siblings_before = kids[:idx]
                            break
                        except ValueError:
                            continue
                    if pid is None:
                        return False
                    for sib_rid in reversed(siblings_before):
                        sib = elem_refId.get(sib_rid)
                        if sib and sib.get('simpleClassName', '') == v:
                            return True
                    return False
            return True

        return [elem for elem in elements if matches(elem)]

    def _escape_xpath_value(self, value: str) -> str:
        """为 XPath 属性值选择最佳引号并转义内容"""
        if "'" in value and '"' not in value:
            return f'"{value}"'
        return f"'{value}'"

    def _make_xpath(self, cls: str, **conditions: Any) -> str:
        """
        构建 XPath 字符串。
        cls: 类名（如 'Button', 'EditText'）
        **conditions: 属性条件，如 text='搜索', refId=5, clickable=True, resourceId='...'
        """
        parts = [f'//{cls}']
        for k, v in conditions.items():
            if v is True:
                parts.append(f'[{k}]')
            elif v is not None and v is not False:
                parts.append(f'[@{k}={self._escape_xpath_value(str(v))}]')
        return ''.join(parts)

    def _parse_refid_from_xpath_segment(self, segment: str) -> Optional[int]:
        """从 xpath 片段（如 'LinearLayout[1][@refId=5]'）中提取 refId"""
        i = 0
        while i < len(segment):
            if segment[i] == '[':
                j = i + 1
                depth = 1
                in_quote = None
                while j < len(segment) and depth > 0:
                    ch = segment[j]
                    if in_quote is not None:
                        if ch == in_quote:
                            in_quote = None
                    else:
                        if ch == '[':
                            depth += 1
                        elif ch == ']':
                            depth -= 1
                        elif ch in ("'", '"'):
                            in_quote = ch
                    j += 1
                inner = segment[i+1:j-1]
                if inner.startswith('@refId='):
                    try:
                        return int(inner[8:].strip("'\""))
                    except ValueError:
                        pass
                i = j
            else:
                i += 1
        return None

    def _build_tree_structure(
        self, tree: List[Dict]
    ) -> Dict[int, Dict]:
        """
        从扁平元素列表构建树结构（parent→children 映射）。

        策略：由于 accessibility xpath 路径中某些中间节点可能没有 @refId，
        无法通过父 segment 的 @refId 找 parent。
        改用「栈」：按 depth 顺序遍历所有元素，维护每层最后一个 refId。
        每遇到更浅深度的元素就 pop，更深就 push。
        包含 depth 和 xpath 前缀以支持前缀匹配。
        每个节点: {elem, parent_ref_id, depth, xpath_prefix, children_ref_ids}
        """
        elem_xpath: Dict[int, str] = {}  # refId -> xpath prefix (不含当前段)
        elem_depth: Dict[int, int] = {}

        for elem in tree:
            ref_id = elem.get('refId')
            if ref_id is None:
                continue
            xpath = elem.get('xpath', '')
            segments = [s for s in xpath.split('/') if s and s != 'WindowRoot']
            depth = len(segments)
            elem_depth[ref_id] = depth
            if len(segments) >= 1:
                prefix = '/' + '/'.join(segments[:-1])
            else:
                prefix = '/WindowRoot'
            elem_xpath[ref_id] = prefix

        stack: List[int] = []  # 按 depth 顺序排列的 refId 列表，stack[depth] = refId
        elem_parent: Dict[int, Optional[int]] = {}

        indexed = [(elem_depth[rid], i, rid) for i, rid in enumerate(elem_depth)]
        indexed.sort(key=lambda x: (x[0], x[1]))

        for depth, _, ref_id in indexed:
            elem_parent[ref_id] = None
            while len(stack) > depth:
                stack.pop()
            if stack:
                elem_parent[ref_id] = stack[-1]
            stack.append(ref_id)

        nodes: Dict[int, Dict] = {}
        for elem in tree:
            ref_id = elem.get('refId')
            if ref_id is None:
                continue
            nodes[ref_id] = {
                'elem': elem,
                'parent_ref_id': elem_parent.get(ref_id),
                'depth': elem_depth.get(ref_id, 0),
                'xpath_prefix': elem_xpath.get(ref_id, ''),
                'children_ref_ids': [],
            }

        for ref_id, parent_ref_id in elem_parent.items():
            if parent_ref_id is not None and parent_ref_id in nodes:
                nodes[parent_ref_id]['children_ref_ids'].append(ref_id)

        return nodes

    def _depth_from_xpath(self, xpath: str) -> int:
        """从 accessibility xpath 计数层数（不含 WindowRoot）"""
        if not xpath:
            return -1
        segments = [s for s in xpath.split('/') if s and s != 'WindowRoot']
        return len(segments)

    def _make_absolute_xpath(self, tree: List[Dict], target_ref_id: int) -> Optional[str]:
        """
        生成绝对路径 XPath：ClassName[1]/ClassName[3]/TargetClassName[N]
        从根节点沿路径到 target，每层按同类 sibling 中的位置编号。
        """
        nodes = self._build_tree_structure(tree)
        if target_ref_id not in nodes:
            return None

        path_ref_ids: List[int] = []
        cur = target_ref_id
        while cur is not None:
            path_ref_ids.append(cur)
            cur = nodes[cur]['parent_ref_id']
        path_ref_ids.reverse()  # 从根到 target

        segments: List[str] = []
        for ref_id in path_ref_ids:
            node = nodes[ref_id]
            elem = node['elem']
            cls = elem.get('simpleClassName', '')
            if not cls:
                continue

            parent_ref_id = node['parent_ref_id']
            if parent_ref_id is None:
                idx = 1
            else:
                parent_node = nodes.get(parent_ref_id)
                if not parent_node:
                    idx = 1
                else:
                    siblings = parent_node['children_ref_ids']
                    same_class_siblings = [
                        sid for sid in siblings
                        if sid in nodes and
                        nodes[sid]['elem'].get('simpleClassName') == cls
                    ]
                    try:
                        idx = same_class_siblings.index(ref_id) + 1
                    except ValueError:
                        idx = 1

            segments.append(f'{cls}[{idx}]')

        return '//' + '/'.join(segments)

    def _strip_refid_annotation(self, segment: str) -> str:
        return re.sub(r'\[@refId=\d+\]', '', segment)

    def _split_debug_xpath(self, xpath: str) -> List[str]:
        return [self._strip_refid_annotation(s) for s in xpath.split('/') if s and s != 'WindowRoot']

    def _extract_path_index(self, segment: str) -> Optional[int]:
        match = re.search(r'\[(\d+)\](?!.*\[\d+\])', segment)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _make_target_segment(
        self,
        elem: Dict,
        fallback_segment: str = '',
        index: Optional[int] = None,
    ) -> str:
        cls = elem.get('simpleClassName', '') or re.sub(r'\[.*$', '', fallback_segment) or 'node'
        text = (elem.get('text', '') or '').strip()
        desc = (elem.get('contentDesc', '') or '').strip()
        rid = (elem.get('resourceId', '') or '').strip()
        same_class_index = index if index and index > 0 else 1

        if desc:
            return f"{cls}[@content-desc={self._escape_xpath_value(desc)}]"
        if cls == 'EditText' and rid:
            return f"{cls}[@resourceId={self._escape_xpath_value(rid)}]"
        if text:
            return f"{cls}[@text={self._escape_xpath_value(text)}]"
        if rid:
            return f"{cls}[@resourceId={self._escape_xpath_value(rid)}]"
        return f"{cls}[{same_class_index}]"

    def _make_target_segment_from_xml(
        self,
        xml_node: ET.Element,
        index: int,
        parent: Optional[ET.Element],
    ) -> str:
        full_cls = xml_node.attrib.get('class', '') or 'node'
        cls = full_cls.split('.')[-1] if '.' in full_cls else full_cls
        text = (xml_node.attrib.get('text', '') or '').strip()
        desc = (xml_node.attrib.get('content-desc', '') or '').strip()
        rid = (xml_node.attrib.get('resource-id', '') or '').strip()

        def predicate_index(attr_name: str, attr_value: str) -> Optional[int]:
            if parent is None:
                return None
            siblings = []
            for child in list(parent):
                child_cls = child.attrib.get('class', '') or ''
                if child_cls != full_cls:
                    continue
                if (child.attrib.get(attr_name, '') or '').strip() != attr_value:
                    continue
                siblings.append(child)
            if len(siblings) <= 1:
                return None
            try:
                return siblings.index(xml_node) + 1
            except ValueError:
                return None

        if desc:
            same_attr_index = predicate_index('content-desc', desc)
            if same_attr_index and same_attr_index > 1:
                return f"{cls}[@content-desc={self._escape_xpath_value(desc)}][{same_attr_index}]"
            return f"{cls}[@content-desc={self._escape_xpath_value(desc)}]"
        if cls == 'EditText' and rid:
            same_attr_index = predicate_index('resource-id', rid)
            if same_attr_index and same_attr_index > 1:
                return f"{cls}[@resourceId={self._escape_xpath_value(rid)}][{same_attr_index}]"
            return f"{cls}[@resourceId={self._escape_xpath_value(rid)}]"
        if text:
            same_attr_index = predicate_index('text', text)
            if same_attr_index and same_attr_index > 1:
                return f"{cls}[@text={self._escape_xpath_value(text)}][{same_attr_index}]"
            return f"{cls}[@text={self._escape_xpath_value(text)}]"
        if rid:
            same_attr_index = predicate_index('resource-id', rid)
            if same_attr_index and same_attr_index > 1:
                return f"{cls}[@resourceId={self._escape_xpath_value(rid)}][{same_attr_index}]"
            return f"{cls}[@resourceId={self._escape_xpath_value(rid)}]"
        return f"{cls}[{index}]"

    def _parse_bounds_string(self, bounds: str) -> Optional[Tuple[int, int, int, int]]:
        match = re.match(r'^\[(\-?\d+),(\-?\d+)\]\[(\-?\d+),(\-?\d+)\]$', bounds.strip())
        if not match:
            return None
        return tuple(int(match.group(i)) for i in range(1, 5))

    def _score_xml_node_match(self, elem: Dict, xml_node: ET.Element) -> int:
        full_cls = xml_node.attrib.get('class', '') or ''
        simple_cls = full_cls.split('.')[-1] if '.' in full_cls else full_cls
        if simple_cls != (elem.get('simpleClassName') or ''):
            return -1

        score = 10
        elem_bounds = self._parse_bounds_string(elem.get('bounds', '') or '')
        xml_bounds = self._parse_bounds_string(xml_node.attrib.get('bounds', '') or '')
        if elem_bounds and xml_bounds:
            if elem_bounds == xml_bounds:
                score += 1000
            else:
                ex1, ey1, ex2, ey2 = elem_bounds
                xx1, xy1, xx2, xy2 = xml_bounds
                ex = (ex1 + ex2) // 2
                ey = (ey1 + ey2) // 2
                if xx1 <= ex <= xx2 and xy1 <= ey <= xy2:
                    score += 200

        elem_text = (elem.get('text', '') or '').strip()
        xml_text = (xml_node.attrib.get('text', '') or '').strip()
        if elem_text:
            if elem_text == xml_text:
                score += 120
            else:
                return -1

        elem_desc = (elem.get('contentDesc', '') or '').strip()
        xml_desc = (xml_node.attrib.get('content-desc', '') or '').strip()
        if elem_desc:
            if elem_desc == xml_desc:
                score += 120
            else:
                return -1

        elem_rid = (elem.get('resourceId', '') or '').strip()
        xml_rid = (xml_node.attrib.get('resource-id', '') or '').strip()
        if elem_rid:
            if elem_rid == xml_rid:
                score += 60
            else:
                return -1

        if elem.get('clickable') and xml_node.attrib.get('clickable') == 'true':
            score += 20
        if elem.get('focusable') and xml_node.attrib.get('focusable') == 'true':
            score += 10

        return score

    def _build_xml_parent_map(self, root: ET.Element) -> Dict[int, Optional[ET.Element]]:
        parent_map: Dict[int, Optional[ET.Element]] = {id(root): None}
        for parent in root.iter():
            for child in list(parent):
                parent_map[id(child)] = parent
        return parent_map

    def _get_xml_node_index(self, node: ET.Element, parent: Optional[ET.Element]) -> int:
        if parent is None:
            return 1
        node_cls = node.attrib.get('class', '') or ''
        siblings = [child for child in list(parent) if (child.attrib.get('class', '') or '') == node_cls]
        try:
            return siblings.index(node) + 1
        except ValueError:
            return 1

    def _find_matching_xml_node(self, elem: Dict, root: ET.Element) -> Optional[ET.Element]:
        best_node: Optional[ET.Element] = None
        best_score = -1
        tie = False

        for node in root.iter('node'):
            score = self._score_xml_node_match(elem, node)
            if score > best_score:
                best_score = score
                best_node = node
                tie = False
            elif score == best_score and score >= 0:
                tie = True

        if best_score < 0 or tie:
            return None
        return best_node

    def build_ui_tree_absolute_xpath(self, tree: List[Dict], elem: Dict) -> Optional[str]:
        xml_text = self.get_ui_tree_xml(force_refresh=True)
        if xml_text:
            try:
                root = ET.fromstring(xml_text)
                node = self._find_matching_xml_node(elem, root)
                if node is not None:
                    parent_map = self._build_xml_parent_map(root)
                    segments: List[str] = []
                    current: Optional[ET.Element] = node
                    while current is not None and current.tag == 'node':
                        parent = parent_map.get(id(current))
                        index = self._get_xml_node_index(current, parent)
                        if current is node:
                            segments.append(self._make_target_segment_from_xml(current, index, parent))
                        else:
                            full_cls = current.attrib.get('class', '') or 'node'
                            cls = full_cls.split('.')[-1] if '.' in full_cls else full_cls
                            segments.append(f"{cls}[{index}]")
                        current = parent if isinstance(parent, ET.Element) else None
                    if segments:
                        segments.reverse()
                        return '/' + '/'.join(segments)
            except ET.ParseError:
                pass

        debug_xpath = elem.get('xpath', '') or ''
        segments = self._split_debug_xpath(debug_xpath)
        if not segments:
            return None

        runtime_absolute = self._make_absolute_xpath(tree, elem.get('refId'))
        runtime_segments = [s for s in (runtime_absolute or '').lstrip('/').split('/') if s]
        runtime_target_segment = runtime_segments[-1] if runtime_segments else ''
        runtime_index = self._extract_path_index(runtime_target_segment)

        segments[-1] = self._make_target_segment(elem, segments[-1], runtime_index)
        return '/' + '/'.join(segments)

    def build_runtime_absolute_xpath(self, tree: List[Dict], elem: Dict) -> Optional[str]:
        ui_tree_absolute = self.build_ui_tree_absolute_xpath(tree, elem)
        if not ui_tree_absolute:
            return None

        segments = [s for s in ui_tree_absolute.lstrip('/').split('/') if s]
        if not segments:
            return None

        return '/hierarchy/' + '/'.join(segments)

    def _ancestor_to_target_path(
        self, tree: List[Dict], target_ref_id: int
    ) -> Optional[str]:
        """
        生成 ancestor-relative XPath：
        从 target 往根走，找到最近的能用非 refId 属性唯一标识的祖先节点，
        然后用 // 连接到 target（带上中间路径的 class+position）。

        例如: //LinearLayout[@text='搜索']//EditText[1]
        """
        nodes = self._build_tree_structure(tree)
        if target_ref_id not in nodes:
            return None

        path_ids: List[int] = []
        cur = target_ref_id
        while cur is not None:
            path_ids.append(cur)
            cur = nodes[cur]['parent_ref_id']
        path_ids.reverse()  # 从根到 target

        for i in range(len(path_ids) - 2, -1, -1):
            ancestor_id = path_ids[i]
            ancestor_node = nodes[ancestor_id]
            ancestor_elem = ancestor_node['elem']
            a_cls = ancestor_elem.get('simpleClassName', '')
            a_text = ancestor_elem.get('text', '') or ''
            a_desc = ancestor_elem.get('contentDesc', '') or ''
            a_rid = ancestor_elem.get('resourceId', '') or ''

            if a_text:
                xp = f'//{a_cls}[@text={self._escape_xpath_value(a_text)}]'
                if len(self.find_by_xpath_all(tree, xp)) == 1:
                    return self._build_descendant_path(
                        tree, nodes, ancestor_id, target_ref_id, xp
                    )

            if a_desc:
                xp = f'//{a_cls}[@contentDescription={self._escape_xpath_value(a_desc)}]'
                if len(self.find_by_xpath_all(tree, xp)) == 1:
                    return self._build_descendant_path(
                        tree, nodes, ancestor_id, target_ref_id, xp
                    )

            if a_rid:
                xp = f'//{a_cls}[@resourceId={self._escape_xpath_value(a_rid)}]'
                if len(self.find_by_xpath_all(tree, xp)) == 1:
                    return self._build_descendant_path(
                        tree, nodes, ancestor_id, target_ref_id, xp
                    )

            if a_text and a_rid:
                xp = f'//{a_cls}[@text={self._escape_xpath_value(a_text)}][@resourceId={self._escape_xpath_value(a_rid)}]'
                if len(self.find_by_xpath_all(tree, xp)) == 1:
                    return self._build_descendant_path(
                        tree, nodes, ancestor_id, target_ref_id, xp
                    )

            if a_text and ancestor_elem.get('clickable'):
                xp = f'//{a_cls}[@text={self._escape_xpath_value(a_text)}][clickable]'
                if len(self.find_by_xpath_all(tree, xp)) == 1:
                    return self._build_descendant_path(
                        tree, nodes, ancestor_id, target_ref_id, xp
                    )

        return None

    def _build_descendant_path(
        self, tree: List[Dict], nodes: Dict[int, Dict],
        ancestor_id: int, target_ref_id: int, ancestor_xp: str
    ) -> str:
        """
        从 ancestor XPath 构建到 target 的 descendant 路径。
        使用 className + sibling index 来区分多个同类型中间节点。
        """
        path_ids: List[int] = []
        cur = target_ref_id
        while cur != ancestor_id:
            path_ids.insert(0, cur)  # 插入到开头（从 ancestor 方向开始）
            cur = nodes[cur]['parent_ref_id']
            if cur is None:
                break

        parts: List[str] = []
        for ref_id in path_ids:
            node = nodes[ref_id]
            elem = node['elem']
            cls = elem.get('simpleClassName', '')
            if not cls:
                continue

            parent_ref = node['parent_ref_id']
            parent_node = nodes.get(parent_ref)
            siblings = parent_node['children_ref_ids'] if parent_node else []
            same_cls = [sid for sid in siblings
                        if sid in nodes and nodes[sid]['elem'].get('simpleClassName') == cls]
            try:
                idx = same_cls.index(ref_id) + 1
            except ValueError:
                idx = 1

            parts.append(f'{cls}[{idx}]')

        if not parts:
            return ancestor_xp

        return ancestor_xp + '//' + '/'.join(parts)

    def generate_xpath_candidates(
        self, elem: Dict, tree: List[Dict]
    ) -> List[Tuple[str, int, str]]:
        """
        为指定元素生成多个候选 XPath，按匹配数量排序。
        输出的 XPath 不含 refId（refId 仅用于内部树结构计算）。

        返回: List[(xpath_string, match_count, strategy_description)]
        strategy 优先级:
          1. text（直接用元素的 text 定位）
          2. contentDesc（图标的描述）
          3. ancestor-relative（祖先节点 + descendant 路径）
          4. className+position（祖先唯一时带兄弟位置索引）
          5. className + resourceId
          6. className + text + resourceId（组合）
          7. className + text + contentDesc（组合）
          8. className 单独兜底
        """
        candidates: List[Tuple[str, int, str]] = []
        seen_xpaths: set = set()

        def add(xp: str, strategy: str) -> None:
            if xp in seen_xpaths:
                return
            seen_xpaths.add(xp)
            matches = self.find_by_xpath_all(tree, xp)
            candidates.append((xp, len(matches), strategy))

        cls = elem.get('simpleClassName', '')
        if not cls:
            return candidates

        ref_id = elem.get('refId')
        text = elem.get('text', '') or ''
        desc = elem.get('contentDesc', '') or ''
        rid = elem.get('resourceId', '') or ''


        if text:
            xp = f'//{cls}[@text={self._escape_xpath_value(text)}]'
            add(xp, 'text')
            if elem.get('clickable'):
                add(f'//{cls}[@text={self._escape_xpath_value(text)}][clickable]', 'text+clickable')

        if desc:
            xp = f'//{cls}[@contentDescription={self._escape_xpath_value(desc)}]'
            add(xp, 'contentDescription')

        if ref_id is not None:
            ar_path = self._ancestor_to_target_path(tree, ref_id)
            if ar_path:
                add(ar_path, 'ancestor-relative')

        if rid:
            add(f'//{cls}[@resourceId={self._escape_xpath_value(rid)}]', 'className+resourceId')

        if text and rid:
            add(f'//{cls}[@text={self._escape_xpath_value(text)}][@resourceId={self._escape_xpath_value(rid)}]',
                'className+text+resourceId')

        if text and desc:
            add(f'//{cls}[@text={self._escape_xpath_value(text)}][@contentDescription={self._escape_xpath_value(desc)}]',
                'className+text+contentDescription')

        if ref_id is not None:
            pos_path = self._ancestor_to_target_path(tree, ref_id)
            if pos_path and '[@refId=' not in pos_path:
                add(pos_path, 'className+position')

        add(f'//{cls}', 'className-only')

        strategy_order = {
            'text': 0,
            'contentDescription': 1,
            'ancestor-relative': 2,
            'className+position': 3,
            'className+resourceId': 4,
            'className+text+resourceId': 5,
            'className+text+contentDescription': 6,
            'text+clickable': 7,
            'className-only': 99,
        }
        candidates.sort(key=lambda c: (
            0 if c[1] == 1 else 1,  # unique first
            strategy_order.get(c[2], 99),  # then by strategy
            c[1]  # then by match count
        ))
        return candidates

    def tap_by_xpath(self, xpath: str) -> bool:
        """使用 Android 运行时 locator 模式点击 XPath。"""
        return self._run_single_operation(
            template_id="tap-xpath",
            operation_type="android.touch.tap",
            parameters={"mode": "locator", "xpath": xpath},
            success_message=f"Tapped XPath [{xpath}]",
            failure_prefix="Tap failed"
        )

    def input_by_xpath(self, xpath: str, text: str) -> bool:
        """使用 Android 运行时 XPath 定位输入元素。"""
        return self._run_single_operation(
            template_id="input-xpath",
            operation_type="android.element.input",
            parameters={
                "xpath": xpath,
                "value": text,
                "clearFirst": True
            },
            success_message=f"Input '{text}' to XPath [{xpath}]",
            failure_prefix="FAILED"
        )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def format_element(elem: Dict) -> str:
    lines = []
    refId = elem.get('refId', '?')
    text = elem.get('text', '')
    desc = elem.get('contentDesc', '')
    rid = elem.get('resourceId', '')
    cls = elem.get('simpleClassName', '')
    x, y = elem.get('x', '?'), elem.get('y', '?')

    lines.append("+" + "-" * 60 + "+")
    lines.append("| refId: {}".format(refId))
    lines.append("|" + "-" * 61 + "|")
    if text:
        lines.append("| text: {}".format(text[:50]))
    if desc:
        lines.append("| contentDesc: {}".format(desc[:50]))
    if rid:
        lines.append("| resourceId: {}".format(rid))
    lines.append("| className: {}".format(cls))
    lines.append("| position: ({}, {})".format(x, y))

    status = []
    if elem.get('clickable'):
        status.append('clickable')
    if elem.get('focusable'):
        status.append('focusable')
    lines.append("| status: {}".format(', '.join(status) if status else 'none'))
    lines.append("|")
    lines.append("| XPath:")
    lines.append("|   {}".format(elem.get('xpath', 'N/A')))
    lines.append("+" + "-" * 60 + "+")
    return '\n'.join(lines)


def print_tree(elements: List[Dict], filter_text: str = None,
               package_name: Optional[str] = None):
    if not elements:
        print("No elements found")
        return

    if filter_text:
        elements = [e for e in elements if
                   filter_text.lower() in (e.get('text', '') or '').lower() or
                   filter_text.lower() in (e.get('contentDesc', '') or '').lower()]

    print()
    print("=" * 70)
    print("  AIVane ARIA Tree - {} elements".format(len(elements)))
    if package_name:
        print("  Current package: {}".format(package_name))
    print("=" * 70)

    for elem in elements:
        refId = elem.get('refId', '?')
        text = elem.get('text', '') or elem.get('contentDesc', '') or '-'
        cls = elem.get('simpleClassName', '')
        x, y = elem.get('x', '?'), elem.get('y', '?')

        flags = []
        if elem.get('clickable'):
            flags.append('click')
        if elem.get('focusable'):
            flags.append('focus')
        flag_str = "[{}]".format(','.join(flags)) if flags else ""
        display_text = text[:25] + "..." if len(str(text)) > 25 else str(text)
        print("  [{:2d}] {:<28} {:<18} ({:4s},{:4s}) {}".format(
            refId, display_text, cls, str(x), str(y), flag_str))

    print("=" * 70)
    print()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class AriaReplSession:
    """
    agent-android REPL 会话。

    命令语法：动词 [+ 副词/参数]
    示例：
      l                    → 列出元素（复用缓存）
      ss                   → 刷新树并列出
      t 5                 → 点击 refId=5
      i 5 你好            → 向 refId=5 输入文本
      s                    → 截图（自动命名）
      s my.png            → 截图到指定路径
      sw d                 → 下滑（down/up/left/right）
      sw d --dur 500 --dist 0.7  → 下滑500ms，距离0.7
      wf 搜索              → 等待"搜索"元素（默认30s）
      wf 搜索 --t 60       → 等待最多60s
      g 5 text            → 获取 refId=5 的 text 属性
      p home              → 按 Home 键
      b                    → 返回
      la com.xingin.xhs    → 启动 App
      f 搜索               → 过滤含"搜索"的元素
      id com.example:id/btn → 按 resourceId 过滤
      ref 5                → refId=5 详情
      x 5                  → refId=5 的 XPath
      raw                  → 切换原始 JSON 输出
      vars                 → 显示会话变量
      set url http://...   → 设置服务器 URL
      set timeout 30       → 设置默认等待超时
      h                    → 显示帮助
      q                    → 退出
    """

    COMMANDS = [
        ('l', 'list',          '列出元素（复用缓存）'),
        ('ss', 'snapshot',     '刷新树并列出'),
        ('f', 'find',          '按文本过滤'),
        ('id', None,           '按 resourceId 过滤'),
        ('ref', None,          '显示元素详情'),
        ('x', 'xpath',        '获取 XPath（显示候选+匹配数）'),
        ('xx', None,           '用自动XPath点击（选最佳唯一候选）'),
        ('vx', 'validatex',    '运行时验证 XPath'),
        ('t', 'tap',          '点击元素 (refId)'),
        ('tx', 'tapx',       '用 XPath 点击元素'),
        ('i', 'input',        '输入文本 (refId text)'),
        ('ix', 'inputx',      '用 XPath 输入文本'),
        ('sw', 'swipe',       '滑动 (d/u/l/r)'),
        ('p', 'press',        '按键 (back/home/menu)'),
        ('b', 'back',         '按返回键'),
        ('wf', 'waitfor',    '等待元素出现'),
        ('g', 'get',         '获取元素属性'),
        ('s', 'screenshot',  '截图'),
        ('la', 'launch',     '启动 App'),
        ('raw', None,        '切换 raw JSON 输出'),
        ('vars', None,        '显示会话变量'),
        ('apps', None,        '列出 launcher apps'),
        ('set', None,         '设置变量 (url/timeout)'),
        ('h', 'help',        '显示帮助'),
        ('q', 'quit',        '退出'),
    ]

    def __init__(self, url: str, history_file: str = None):
        self.client = AriaTreeClient(url)
        self._tree: Optional[List[Dict]] = None   # 当前缓存的树
        self._raw_output: bool = False            # raw JSON 输出开关
        self._timeout: int = 30                  # 默认等待超时（秒）
        self._prompt: str = "aria> "
        self.variables: Dict[str, Any] = {}      # 会话变量（LAST_XPATH 等）

        if _HAS_READLINE and history_file:
            try:
                readline.read_history_file(history_file)
            except FileNotFoundError:
                pass
            self._history_file = history_file

        self._aliases: Dict[str, str] = {}
        for short, full, _ in self.COMMANDS:
            if short:
                self._aliases[short] = full or short
            if full:
                self._aliases[full] = full

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def run(self):
        self._print_banner()
        while True:
            try:
                line = self._readline()
                if line is None:  # EOF / Ctrl+D
                    break
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                result = self._execute_line(line)
                if result is _REPL_EXIT:
                    break

            except KeyboardInterrupt:
                print()  # 换行
                print("  (Ctrl+C: 输入 q 退出)", file=sys.stderr)
                continue
            except EOFError:
                break
            except Exception:
                print(f"  [!] Error: {traceback.format_exc(limit=3)}", file=sys.stderr)

        self._save_history()
        print("Goodbye!")

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _parse_line(self, line: str) -> Tuple[str, List[str]]:
        """
        解析一行命令。
        返回 (command_name, [arg1, arg2, ...])
        支持:
          - 空白符分隔
          - 双引号/单引号字符串
          - --flag value 风格参数
        """
        stripped = line.strip()
        if not stripped:
            return '', []

        first, _, remainder = stripped.partition(' ')
        cmd = first
        remainder = remainder.strip()

        if cmd in ('vx', 'validatex', 'tx', 'tapx'):
            return cmd, [remainder] if remainder else []

        if cmd in ('ix', 'inputx'):
            if not remainder:
                return cmd, []
            if ' -- ' in remainder:
                xpath, text = remainder.split(' -- ', 1)
                xpath = xpath.strip()
                text = text.strip()
                return cmd, [xpath, text] if xpath and text else [xpath] if xpath else []
            xpath, sep, text = remainder.rpartition(' ')
            if sep:
                xpath = xpath.strip()
                text = text.strip()
                return cmd, [xpath, text] if xpath and text else [remainder]
            return cmd, [remainder]

        tokens = shlex.split(line, posix=False)
        if not tokens:
            return '', []
        cmd = tokens[0]
        args = tokens[1:]

        return cmd, args

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _execute_line(self, line: str) -> Any:
        cmd, args = self._parse_line(line)

        resolved = self._aliases.get(cmd, cmd)
        handler_name = f"_cmd_{resolved}"
        handler = getattr(self, handler_name, None)
        if handler is None:
            self._print_error(f"Unknown command: {cmd!r}.  Type 'h' for help.")
            return False

        try:
            return handler(args)
        except TypeError as e:
            self._print_error(f"Usage: {e}")
            return False

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _readline(self) -> Optional[str]:
        if _HAS_READLINE:
            return input(self._prompt)
        else:
            return input(self._prompt)

    def _add_history(self, line: str):
        if _HAS_READLINE:
            try:
                readline.add_history(line)
            except Exception:
                pass

    def _save_history(self):
        if _HAS_READLINE and hasattr(self, '_history_file'):
            try:
                readline.write_history_file(self._history_file)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _ensure_tree(self, force=False) -> Optional[List[Dict]]:
        """确保有缓存的树（必要时刷新）"""
        if force or self._tree is None:
            self._tree = self.client.get_ui_elements(force_refresh=True)
        return self._tree

    def _invalidate_tree(self):
        """操作后使树缓存失效"""
        self._tree = None
        self.client._local_tree = None

    def _current_package_label(self) -> str:
        pkg = self.client.get_current_package_name()
        return pkg or "unknown"

    def _print_tree(self, elements: List[Dict], title: str = None):
        """格式化打印元素列表"""
        print()
        n = len(elements)
        title = title or f"ARIA Tree - {n} elements"
        print(f"  ╭{'─' * 66}╮")
        print(f"  │ {title:<64} │")
        print(f"  ╰{'─' * 66}╯")
        print(f"  Current package: {self._current_package_label()}")
        for e in elements:
            rid = e.get('refId', '?')
            text = str(e.get('text', '') or e.get('contentDesc', '') or '-')
            cls = e.get('simpleClassName', '')
            x, y = e.get('x', '?'), e.get('y', '?')
            flags = []
            if e.get('clickable'): flags.append('click')
            if e.get('focusable'): flags.append('focus')
            flag = f"[{','.join(flags)}]" if flags else ""
            text_disp = text[:22] + '…' if len(text) > 22 else text
            print(f"  [{rid:>2}] {text_disp:<24} {cls:<16} ({str(x):>4},{str(y):>4}) {flag}")
        print()

    def _runtime_validate_candidates(
        self, candidates: List[Tuple[str, int, str]]
    ) -> List[Tuple[str, int, str, Optional[Dict[str, Any]]]]:
        """使用 Android 运行时 evaluator 验证候选 XPath。"""
        validated: List[Tuple[str, int, str, Optional[Dict[str, Any]]]] = []
        strategy_order = {
            'text': 0,
            'contentDescription': 1,
            'ancestor-relative': 2,
            'className+position': 3,
            'className+resourceId': 4,
            'className+text+resourceId': 5,
            'className+text+contentDescription': 6,
            'text+clickable': 7,
            'className-only': 99,
        }

        for xp, _, strategy in candidates:
            info = self.client.validate_xpath_runtime(xp)
            count = info.get('count', -1) if info else -1
            validated.append((xp, count, strategy, info))

        validated.sort(key=lambda c: (
            0 if c[1] == 1 else 1,
            0 if c[1] >= 0 else 2,
            strategy_order.get(c[2], 99),
            c[1] if c[1] >= 0 else 999999,
        ))
        return validated

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _cmd_list(self, args: List[str]) -> bool:
        """l [n]  — 列出前 n 个元素（默认全部）"""
        limit = None
        if args and args[0].isdigit():
            limit = int(args[0])
        tree = self._ensure_tree()
        if not tree:
            self._print_error(f"Failed to get ARIA tree (package={self._current_package_label()})")
            return False
        elems = tree[:limit] if limit else tree
        self._print_tree(elems)
        return True

    def _cmd_snapshot(self, args: List[str]) -> bool:
        """ss — 强制刷新树并列出"""
        tree = self._ensure_tree(force=True)
        if not tree:
            self._print_error(f"Failed to get ARIA tree (package={self._current_package_label()})")
            return False
        self._print_tree(tree, f"ARIA Tree (refreshed) - {len(tree)} elements")
        return True

    def _cmd_l(self, args: List[str]) -> bool:
        return self._cmd_list(args)

    def _cmd_ss(self, args: List[str]) -> bool:
        return self._cmd_snapshot(args)

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _cmd_find(self, args: List[str]) -> bool:
        """f [text] — 按文本过滤元素"""
        if not args:
            self._print_error("Usage: f <text>")
            return False
        text = ' '.join(args)
        tree = self._ensure_tree()
        if not tree:
            return False
        results = self.client.find_by_text(tree, text)
        if not results:
            print(f"  [!] No elements matching: {text!r}")
            return False
        self._print_tree(results, f"Find: '{text}' ({len(results)} matches)")
        return True

    def _cmd_f(self, args: List[str]) -> bool:
        return self._cmd_find(args)

    def _cmd_id(self, args: List[str]) -> bool:
        """id <resourceId> — 按 resourceId 过滤"""
        if not args:
            self._print_error("Usage: id <resourceId>")
            return False
        rid = ' '.join(args)
        tree = self._ensure_tree()
        if not tree:
            return False
        results = self.client.find_by_resourceId(tree, rid)
        if not results:
            print(f"  [!] No elements with resourceId: {rid!r}")
            return False
        self._print_tree(results, f"resourceId: {rid!r} ({len(results)} matches)")
        return True

    def _cmd_ref(self, args: List[str]) -> bool:
        """ref <N> — 显示 refId 详情"""
        if not args or not args[0].isdigit():
            self._print_error("Usage: ref <refId>")
            return False
        refId = int(args[0])
        tree = self._ensure_tree()
        if not tree:
            return False
        elem = self.client.find_by_refId(tree, refId)
        if not elem:
            print(f"  [!] Element refId={refId} not found ({len(tree)} elements in tree)")
            return False
        print(format_element(elem))
        return True

    def _cmd_xpath(self, args: List[str]) -> bool:
        """x <N> [idx] — 获取元素 XPath（按 Android 运行时匹配数量验证）"""
        if not args or not args[0].isdigit():
            self._print_error("Usage: x <refId> [候选序号]")
            return False
        refId = int(args[0])
        tree = self._ensure_tree()
        if not tree:
            return False
        elem = self.client.find_by_refId(tree, refId)
        if not elem:
            print(f"  [!] Element refId={refId} not found")
            return False

        raw_candidates = self.client.generate_xpath_candidates(elem, tree)
        if not raw_candidates:
            print(f"  [!] No XPath candidates generated")
            return False
        candidates = self._runtime_validate_candidates(raw_candidates)
        ui_tree_absolute = self.client.build_ui_tree_absolute_xpath(tree, elem)
        runtime_absolute = self.client.build_runtime_absolute_xpath(tree, elem)
        runtime_absolute_info = self.client.validate_xpath_runtime(runtime_absolute) if runtime_absolute else None

        print()
        print(f"  refId={refId}  text='{elem.get('text', '')[:30]}'  "
              f"class={elem.get('simpleClassName', '')}")
        if ui_tree_absolute:
            print(f"  UI tree 绝对路径: {ui_tree_absolute}")
        if runtime_absolute:
            runtime_count = runtime_absolute_info.get('count') if runtime_absolute_info else '?'
            print(f"  Runtime 绝对路径: {runtime_absolute}  (match={runtime_count})")
        print(f"  {'─' * 60}")
        print(f"  {'序号':<4} {'运行时匹配':<10} {'XPath'}")
        print(f"  {'─' * 60}")

        for i, (xp, count, strategy, info) in enumerate(candidates):
            badge = ''
            if count < 0:
                badge = ' ❓ 错误'
            elif count == 1:
                badge = ' ✅ 唯一'
            elif count <= 3:
                badge = f' ⚠️  {count}个'
            else:
                badge = f' ❌  {count}个'
            xp_display = xp if len(xp) <= 55 else xp[:52] + '...'
            print(f"  [{i}] {badge:<8} {xp_display}  ({strategy})")
            if info and count == 1:
                summary = info.get('text') or info.get('contentDescription') or '-'
                print(f"      → {info.get('className') or '-'} | {summary!r}")

        print(f"  {'─' * 60}")
        best = candidates[0]
        if best[1] == 1:
            print(f"  ✓ 推荐: {best[0]}")
            print(f"    策略={best[2]}，运行时匹配 1 个元素（唯一）")
        elif best[1] < 0:
            print(f"  ⚠  最佳候选验证失败，建议先用 'vx <xpath>' 单独排查")
            print(f"     推荐: {best[0]}")
        else:
            print(f"  ⚠  最佳候选运行时匹配 {best[1]} 个元素，可能不够唯一")
            print(f"     推荐: {best[0]}")

        if len(args) >= 2 and args[1].isdigit():
            idx = int(args[1])
            if 0 <= idx < len(candidates):
                chosen = candidates[idx]
                print(f"\n  使用 [{idx}] {chosen[0]}")
                print(f"  策略: {chosen[2]}，运行时匹配 {chosen[1]} 个元素")
                if chosen[1] > 1:
                    print(f"  [!] 警告: 此 XPath 运行时匹配 {chosen[1]} 个元素，点击可能不精确！")
                self.variables['LAST_XPATH'] = chosen[0]
                self.variables['LAST_XPATH_COUNT'] = chosen[1]
                self.variables['LAST_XPATH_STRATEGY'] = chosen[2]
                self.variables['LAST_XPATH_RUNTIME'] = chosen[3]
            else:
                print(f"  [!] 序号 {idx} 超出范围 (0-{len(candidates)-1})")
        else:
            self.variables['LAST_XPATH'] = best[0]
            self.variables['LAST_XPATH_COUNT'] = best[1]
            self.variables['LAST_XPATH_STRATEGY'] = best[2]
            self.variables['LAST_XPATH_RUNTIME'] = best[3]
        self.variables['LAST_UI_TREE_ABSOLUTE_XPATH'] = ui_tree_absolute
        self.variables['LAST_RUNTIME_ABSOLUTE_XPATH'] = runtime_absolute
        self.variables['LAST_RUNTIME_ABSOLUTE_INFO'] = runtime_absolute_info
        return True

    def _cmd_x(self, args: List[str]) -> bool:
        return self._cmd_xpath(args)

    def _cmd_xx(self, args: List[str]) -> bool:
        """xx <N> — 用自动生成的唯一 XPath 点击元素（优先选唯一匹配）"""
        if not args or not args[0].isdigit():
            self._print_error("Usage: xx <refId>")
            return False
        refId = int(args[0])
        tree = self._ensure_tree()
        if not tree:
            return False
        elem = self.client.find_by_refId(tree, refId)
        if not elem:
            print(f"  [!] Element refId={refId} not found")
            return False

        raw_candidates = self.client.generate_xpath_candidates(elem, tree)
        if not raw_candidates:
            print(f"  [!] No XPath candidates generated")
            return False
        candidates = self._runtime_validate_candidates(raw_candidates)

        unique: Optional[Tuple[str, int, str, Optional[Dict[str, Any]]]] = None
        for xp, count, strategy, info in candidates:
            if count == 1:
                unique = (xp, count, strategy, info)
                break

        if unique:
            xp, count, strategy, _ = unique
            print(f"  ✓ refId={refId} → XPath (唯一匹配): {xp}")
            print(f"    策略: {strategy}")
        else:
            xp, count, strategy, _ = candidates[0]
            print(f"  [!] refId={refId}: 没有找到唯一匹配的 XPath！")
            print(f"  ⚠  使用最佳候选: {xp}")
            print(f"     策略: {strategy}，运行时匹配 {count} 个元素")
            print(f"  ❌ 点击被拒绝 — XPath 不够唯一，可能误触！")
            print(f"  ")
            print(f"  提示: 用 'x {refId}' 查看所有候选，用 'x {refId} <序号>' 选中非唯一 XPath")
            return False

        ok = self.client.tap_by_xpath(xp)
        if ok:
            self._invalidate_tree()
        return ok

    def _cmd_xx_alias(self, args: List[str]) -> bool:
        """tapx-auto <refId> — 同 xx"""
        return self._cmd_xx(args)

    def _cmd_validatex(self, args: List[str]) -> bool:
        """vx <xpath> — 运行时验证 XPath"""
        if not args:
            self._print_error("Usage: vx <xpath>")
            return False
        xpath = ' '.join(args)
        info = self.client.validate_xpath_runtime(xpath)
        if not info:
            print(f"  [!] Runtime validation failed: {xpath}")
            return False

        print(f"  XPath: {xpath}")
        print(f"  Runtime match count: {info.get('count')}")
        if info.get('count') == 1:
            print(f"  Class: {info.get('className') or '-'}")
            print(f"  Text:  {info.get('text') or '-'}")
            print(f"  Desc:  {info.get('contentDescription') or '-'}")
            print(f"  Bounds:{info.get('bounds') or '-'}")
        return True

    def _cmd_vx(self, args: List[str]) -> bool:
        return self._cmd_validatex(args)

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _cmd_tap(self, args: List[str]) -> bool:
        """t <refId> — 点击元素"""
        if not args or not args[0].isdigit():
            self._print_error("Usage: t <refId>")
            return False
        refId = int(args[0])
        ok = self.client.tap_element(refId)
        if ok:
            self._invalidate_tree()
        return ok

    def _cmd_t(self, args: List[str]) -> bool:
        return self._cmd_tap(args)

    def _cmd_input(self, args: List[str]) -> bool:
        """i <refId> <text> — 向元素输入文本"""
        if len(args) < 2 or not args[0].isdigit():
            self._print_error("Usage: i <refId> <text>")
            return False
        refId = int(args[0])
        text = ' '.join(args[1:])
        ok = self.client.input_to_element(refId, text)
        if ok:
            self._invalidate_tree()
        return ok

    def _cmd_i(self, args: List[str]) -> bool:
        return self._cmd_input(args)

    def _cmd_tapx(self, args: List[str]) -> bool:
        """tx <xpath> — 用 XPath 点击元素"""
        if not args:
            self._print_error("Usage: tx <xpath>")
            self._print_error("  例: tx //EditText[@text='搜索']")
            self._print_error("  例: tx //Button[@text='OK']")
            self._print_error("  例: tx //TextView[@contentDescription='搜索'][clickable]")
            return False
        xpath = ' '.join(args)
        ok = self.client.tap_by_xpath(xpath)
        if ok:
            self._invalidate_tree()
        return ok

    def _cmd_tx(self, args: List[str]) -> bool:
        return self._cmd_tapx(args)

    def _cmd_inputx(self, args: List[str]) -> bool:
        """ix <xpath> <text> — 用 XPath 向输入框输入文本"""
        if len(args) < 2:
            self._print_error("Usage: ix <xpath> <text>")
            self._print_error("  例: ix //EditText[@text='搜索'] hello")
            return False
        xpath = args[0]
        text = ' '.join(args[1:])
        ok = self.client.input_by_xpath(xpath, text)
        if ok:
            self._invalidate_tree()
        return ok

    def _cmd_ix(self, args: List[str]) -> bool:
        return self._cmd_inputx(args)

    def _cmd_swipe(self, args: List[str]) -> bool:
        """sw <d|u|l|r> [--dur N] [--dist N] — 滑动"""
        if not args or args[0] not in ('d', 'u', 'l', 'r',
                                          'down', 'up', 'left', 'right'):
            self._print_error("Usage: sw <d|u|l|r> [--dur N] [--dist N]")
            return False
        direction_map = {'d': 'down', 'u': 'up', 'l': 'left', 'r': 'right'}
        direction = direction_map.get(args[0], args[0])

        duration = 300
        distance = 0.5
        i = 1
        while i < len(args):
            if args[i] == '--dur' and i + 1 < len(args):
                duration = int(args[i + 1]); i += 2
            elif args[i] == '--dist' and i + 1 < len(args):
                distance = float(args[i + 1]); i += 2
            else:
                i += 1

        ok = self.client.swipe(direction, duration, distance)
        if ok:
            self._invalidate_tree()
        return ok

    def _cmd_sw(self, args: List[str]) -> bool:
        return self._cmd_swipe(args)

    def _cmd_press(self, args: List[str]) -> bool:
        """p <key> — 按键 (back/home/menu)"""
        if not args:
            self._print_error("Usage: p <back|home|menu>")
            return False
        ok = self.client.press_key(args[0])
        if ok:
            self._invalidate_tree()
        return ok

    def _cmd_p(self, args: List[str]) -> bool:
        return self._cmd_press(args)

    def _cmd_back(self, args: List[str]) -> bool:
        """b — 按返回键"""
        ok = self.client.press_back()
        if ok:
            self._invalidate_tree()
        return ok

    def _cmd_b(self, args: List[str]) -> bool:
        return self._cmd_back(args)

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _cmd_waitfor(self, args: List[str]) -> bool:
        """wf <text> [--t N] — 等待元素出现"""
        if not args or args[0].startswith('--'):
            self._print_error("Usage: wf <text> [--t N]")
            return False

        text = args[0]
        timeout = self._timeout
        i = 1
        while i < len(args):
            if args[i] == '--t' and i + 1 < len(args):
                timeout = int(args[i + 1]); i += 2
            else:
                i += 1

        print(f"  Waiting for: {text!r} (timeout={timeout}s)...")
        elem = self.client.wait_for_element(text=text, timeout=timeout)
        if elem:
            print(f"  ✓ Found refId={elem.get('refId')}: "
                  f"text={elem.get('text', '')!r} "
                  f"at ({elem.get('x')}, {elem.get('y')})")
            self._invalidate_tree()
            return True
        else:
            print(f"  ✗ Timeout after {timeout}s")
            return False

    def _cmd_wf(self, args: List[str]) -> bool:
        return self._cmd_waitfor(args)

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _cmd_get(self, args: List[str]) -> bool:
        """g <refId> <attr> — 获取元素属性"""
        if len(args) < 2:
            self._print_error("Usage: g <refId> <attr>  (attr: text/class/bounds/x/y/xpath/...)")
            return False
        refId = int(args[0])
        attr = args[1]
        value = self.client.get_attribute(refId, attr)
        return value is not None

    def _cmd_g(self, args: List[str]) -> bool:
        return self._cmd_get(args)

    def _cmd_screenshot(self, args: List[str]) -> bool:
        """s [path] — 截图"""
        path = args[0] if args else None
        result = self.client.screenshot(output_path=path)
        if result:
            print(f"  ✓ {result}")
            return True
        return False

    def _cmd_s(self, args: List[str]) -> bool:
        return self._cmd_screenshot(args)

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _cmd_launch(self, args: List[str]) -> bool:
        """la <package> — 启动 App"""
        if not args:
            self._print_error("Usage: la <package>")
            return False
        package = args[0]
        ok = self.client.launch_app(package)
        if ok:
            self._invalidate_tree()
        return ok

    def _cmd_la(self, args: List[str]) -> bool:
        return self._cmd_launch(args)

    def _cmd_apps(self, args: List[str]) -> bool:
        """apps — 列出 launcher apps"""
        apps = self.client.list_launcher_apps()
        if apps is None:
            self._print_error("Failed to fetch launcher apps.")
            return False
        if not apps:
            print("  No launcher apps returned.")
            return True
        print("Launcher apps:")
        for index, app in enumerate(apps, start=1):
            print(f"  [{index:02d}] {_format_launcher_app(app)}")
        return True

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _cmd_raw(self, args: List[str]) -> bool:
        """raw — 切换 raw JSON 输出"""
        self._raw_output = not self._raw_output
        print(f"  Raw JSON output: {'ON' if self._raw_output else 'OFF'}")
        return True

    def _cmd_vars(self, args: List[str]) -> bool:
        """vars — 显示会话变量"""
        print("  Session:")
        print(f"    URL:      {self.client.base_url}")
        print(f"    Timeout:  {self._timeout}s")
        print(f"    RawJSON:  {'ON' if self._raw_output else 'OFF'}")
        print(f"    Cached:   {'YES' if self._tree is not None else 'NO'}")
        if self._tree:
            print(f"    Elements: {len(self._tree)}")
        return True

    def _cmd_set(self, args: List[str]) -> bool:
        """set <url|timeout> <value> — 设置会话变量"""
        if len(args) < 2:
            self._print_error("Usage: set <url|timeout> <value>")
            return False
        key, value = args[0], ' '.join(args[1:])
        if key == 'url':
            trimmed_value = value.strip()
            if not trimmed_value:
                self._print_error("URL cannot be empty")
                return False
            self.client = AriaTreeClient(trimmed_value)
            print(f"  URL set to: {trimmed_value}")
            try:
                save_url_to_config(trimmed_value)
                print(f"  Persisted to {CONFIG_FILE_PATH}")
            except OSError as exc:
                print(f"  Warning: could not save URL to {CONFIG_FILE_PATH}: {exc}", file=sys.stderr)
        elif key == 'timeout':
            self._timeout = int(value)
            print(f"  Timeout set to: {self._timeout}s")
        else:
            self._print_error(f"Unknown variable: {key!r}.  Available: url, timeout")
            return False
        return True

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _cmd_help(self, args: List[str]) -> bool:
        """h — 显示帮助"""
        self._print_help()
        return True

    def _cmd_h(self, args: List[str]) -> bool:
        return self._cmd_help(args)

    def _cmd_quit(self, args: List[str]) -> Any:
        """q — 退出"""
        return _REPL_EXIT

    def _cmd_q(self, args: List[str]) -> Any:
        return self._cmd_quit(args)

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------

    def _print_help(self):
        lines = [
            "",
            "  agent-android REPL v5.4 — Command Reference",
            "  ─" + "─" * 66,
            "",
            "  Browse",
            "    l [n]             列出元素（n=显示前n个，reuse缓存）",
            "    ss                刷新树并列出（force refresh）",
            "    f <text>          按文本过滤元素",
            "    id <resourceId>   按 resourceId 过滤",
            "    ref <N>           显示 refId=N 的详细信息",
            "    x <N> [idx]       显示 refId=N 的 XPath 候选列表（按运行时匹配数验证）",
            "                       用 'x <N> <idx>' 选中特定候选并存为 LAST_XPATH",
            "    xx <N>            选唯一候选 XPath 自动点击（无唯一候选则拒绝）",
            "    vx <xpath>        运行时验证 XPath 的匹配数量",
            "",
            "  Interact",
            "    t <N>             点击 refId=N 的元素",
            "    tx <xpath>        用 XPath 点击元素",
            "                       例: tx //Button[@text='搜索']",
            "                       例: tx //EditText[@text='搜索']",
            "    i <N> <text>      向 refId=N 输入文本",
            "    ix <xpath> <text> 用 XPath 输入文本",
            "                       例: ix //EditText[@text='搜索'] 你好",
            "    sw <d|u|l|r> [--dur N] [--dist N]",
            "                       滑动（d=down, u=up, l=left, r=right）",
            "    p <key>           按键 (back/home/menu)",
            "    b                  按返回键",
            "",
            "  Wait",
            "    wf <text> [--t N]  等待元素出现（默认30s超时）",
            "",
            "  Info",
            "    g <N> <attr>     获取 refId=N 的属性",
            "                       (text/class/bounds/x/y/xpath/selector/...)",
            "    s [path]          截图（无参数=自动命名）",
            "    la <package>      启动 App（如 com.xingin.xhs）",
            "",
            "  Session",
            "    raw                切换 raw JSON 输出",
            "    vars               显示会话变量",
            "    apps               列出 launcher apps",
            "    set url <url>      切换服务器 URL",
            "    set timeout <N>    设置默认等待超时（秒）",
            "",
            "  Exit",
            "    q                  退出 REPL",
            "    h                  显示本帮助",
            "",
            "  Shortcuts: l→list, ss→snapshot, t→tap, tx→tapx, xx→tapx-auto,",
            "              i→input, ix→inputx, sw→swipe, p→press, b→back,",
            "              wf→waitfor, g→get, s→screenshot, la→launch, vx→validatex,",
            "              ref→ref, x→xpath, f→find, h→help, q→quit",
            "",
        ]
        print('\n'.join(lines))

    def _print_banner(self):
        print()
        print("  agent-android REPL v5.4  —  Android UI Automation REPL")
        print(f"  Server: {self.client.base_url}")
        print("  Type 'h' for help, 'q' to quit.")
        print()

    def _print_error(self, msg: str):
        print(f"  [!] {msg}", file=sys.stderr)
def main():
    parser = argparse.ArgumentParser(
        description='agent-android v0.1 — Android UI Automation + following-sibling:: axis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--repl', '-i', action='store_true',
                       help='Enter REPL interactive mode (recommended)')
    parser.add_argument('--url', '-u', default=None,
                       help='AIVane server URL (command-line overrides saved config)')
    parser.add_argument('--wait', '-w', type=int, default=0,
                       help='Wait N seconds before fetching ARIA tree')
    parser.add_argument('--no-cache', action='store_true',
                       help='Force refresh ARIA tree (bypass cache)')

    parser.add_argument('--wait-for', type=str, metavar='TEXT',
                       help='Wait for element with text matching to appear')
    parser.add_argument('--timeout', '-t', type=int, default=30,
                       help='Max wait time for --wait-for (default: 30s)')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--list', '-l', action='store_true', help='List all elements')
    group.add_argument('--screenshot', '-s', nargs='?', const='_auto_', metavar='OUTPUT_PATH',
                       help='Capture screenshot. Optional: output file path')
    group.add_argument('--swipe', type=str, metavar='DIRECTION',
                       help='Swipe direction: up/down/left/right')
    group.add_argument('--tap', type=int, metavar='REFID', help='Tap element by refId')
    group.add_argument('--input', nargs=2, metavar=('REFID', 'TEXT'),
                      help='Input text to element by refId')
    group.add_argument('--launch', '-a', type=str, metavar='PACKAGE', help='Launch app')
    group.add_argument('--back', action='store_true', help='Press back button')
    group.add_argument('--apps', action='store_true', help='List launcher apps from /api/apps')
    group.add_argument('--press', type=str, metavar='KEY',
                      help='Press key: back / home / menu / enter')
    group.add_argument('--get-attr', nargs=2, metavar=('REFID', 'ATTR'),
                      help='Get element attribute by refId (text/className/bounds/...)')
    group.add_argument('--refId', '-r', type=int, metavar='N', help='Get element details')
    group.add_argument('--xpath', '-x', type=int, metavar='N', help='Get element XPath')
    group.add_argument('--id', type=str, metavar='RESOURCE_ID', help='Query by resourceId')
    group.add_argument('--text', type=str, metavar='TEXT', help='Query by text')
    group.add_argument('--inputs', action='store_true', help='List all input fields')

    parser.add_argument('--duration', type=int, default=300,
                       help='Swipe duration in ms (default: 300)')
    parser.add_argument('--distance', type=float, default=0.5,
                       help='Swipe distance ratio 0.0-1.0 (default: 0.5)')

    parser.add_argument('--quality', '-q', type=int, default=80,
                       help='Screenshot quality 1-100 (default: 80)')

    parser.add_argument('--filter', '-f', type=str, help='Filter elements by text')
    parser.add_argument('--raw', action='store_true', help='Output raw JSON')
    parser.add_argument('--output', '-o', type=str, help='Save ARIA tree to JSON file')

    args = parser.parse_args()
    url = require_base_url(args.url)

    if args.repl:
        hist = os.path.expanduser('~/.agent-android-history')
        session = AriaReplSession(url=url, history_file=hist)
        session.run()
        sys.exit(0)

    client = AriaTreeClient(url)

    force_refresh = args.no_cache

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    if args.back:
        success = client.press_back()
        sys.exit(0 if success else 1)

    if args.press:
        success = client.press_key(args.press)
        sys.exit(0 if success else 1)

    if args.launch:
        success = client.launch_app(args.launch)
        sys.exit(0 if success else 1)

    if args.apps:
        apps = client.list_launcher_apps()
        if apps is None:
            print("Failed to fetch launcher apps", file=sys.stderr)
            sys.exit(1)
        if not apps:
            print("No launcher apps returned.")
            sys.exit(0)
        print("Launcher apps:")
        for index, app in enumerate(apps, start=1):
            print(f"  [{index:02d}] {_format_launcher_app(app)}")
        sys.exit(0)

    if args.screenshot is not None:
        output_path = None if args.screenshot == '_auto_' else args.screenshot
        result = client.screenshot(output_path=output_path, quality=args.quality)
        sys.exit(0 if result else 1)

    if args.swipe:
        success = client.swipe(direction=args.swipe, duration=args.duration,
                               distance=args.distance)
        sys.exit(0 if success else 1)

    if args.tap is not None:
        success = client.tap_element(args.tap)
        sys.exit(0 if success else 1)

    if args.input:
        refId = int(args.input[0])
        text = args.input[1]
        success = client.input_to_element(refId, text)
        sys.exit(0 if success else 1)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    if args.wait_for:
        print(f"Waiting for element '{args.wait_for}' (timeout={args.timeout}s)...",
              file=sys.stderr)
        elem = client.wait_for_element(text=args.wait_for, timeout=args.timeout)
        if elem:
            refId = elem.get('refId')
            print(f"refId={refId} found: text='{elem.get('text', '')}' "
                  f"class={elem.get('simpleClassName', '')} "
                  f"at ({elem.get('x', '?')}, {elem.get('y', '?')})")
            sys.exit(0)
        else:
            sys.exit(1)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    print("Fetching ARIA tree...", file=sys.stderr)
    elements = client.get_ui_elements(wait=args.wait, force_refresh=force_refresh)
    if not elements:
        print("Failed to get ARIA tree", file=sys.stderr)
        sys.exit(1)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(elements, f, ensure_ascii=False, indent=2)
        print("ARIA tree saved to: {}".format(args.output), file=sys.stderr)

    if args.inputs:
        input_elements = client.find_input_elements(elements)
        if not input_elements:
            print("No input fields found")
            sys.exit(0)
        print("\n" + "=" * 70)
        print("  Input Fields - {} elements".format(len(input_elements)))
        print("=" * 70)
        for elem in input_elements:
            refId = elem.get('refId', '?')
            text = elem.get('text', '') or elem.get('contentDesc', '') or '-'
            cls = elem.get('simpleClassName', '')
            x, y = elem.get('x', '?'), elem.get('y', '?')
            editable = 'editable' if elem.get('editable') else ''
            focusable = 'focusable' if elem.get('focusable') else ''
            print("  [{:2d}] {:<28} {:<18} ({:4s},{:4s}) [{}, {}]".format(
                refId, str(text)[:28], cls, str(x), str(y), editable, focusable))
        print("=" * 70)
        sys.exit(0)

    # --get-attr
    if args.get_attr:
        refId = int(args.get_attr[0])
        attr = args.get_attr[1]
        value = client.get_attribute(refId, attr)
        if value is not None:
            print(value)
            sys.exit(0)
        else:
            sys.exit(1)

    results = elements

    if args.refId:
        elem = client.find_by_refId(elements, args.refId)
        if elem:
            print(format_element(elem))
        else:
            print("Element with refId={} not found".format(args.refId))
            sys.exit(1)

    elif args.xpath:
        elem = client.find_by_refId(elements, args.xpath)
        if elem:
            print(elem.get('xpath', ''))
        else:
            print("Element with refId={} not found".format(args.xpath))
            sys.exit(1)

    elif args.id:
        results = client.find_by_resourceId(elements, args.id)
        if not results:
            print("No elements with resourceId={}".format(args.id))

    elif args.text:
        results = client.find_by_text(elements, args.text)
        if not results:
            print("No elements with text containing '{}'".format(args.text))

    else:
        args.list = True

    if args.list or args.text or args.id:
        if args.raw:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            print_tree(results, args.filter, client.get_current_package_name())


if __name__ == '__main__':
    main()


