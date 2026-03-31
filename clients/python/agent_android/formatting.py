from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


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
    return f"{label} - {package}{extra_text} [{activity}]"


def format_element(elem: Dict[str, Any]) -> str:
    lines = []
    ref_id = elem.get("refId", "?")
    text = elem.get("text", "")
    desc = elem.get("contentDesc", "")
    resource_id = elem.get("resourceId", "")
    cls = elem.get("simpleClassName", "")
    x, y = elem.get("x", "?"), elem.get("y", "?")

    lines.append("+" + "-" * 60 + "+")
    lines.append("| refId: {}".format(ref_id))
    lines.append("|" + "-" * 61 + "|")
    if text:
        lines.append("| text: {}".format(text[:50]))
    if desc:
        lines.append("| contentDesc: {}".format(desc[:50]))
    if resource_id:
        lines.append("| resourceId: {}".format(resource_id))
    lines.append("| className: {}".format(cls))
    lines.append("| position: ({}, {})".format(x, y))

    status = []
    if elem.get("clickable"):
        status.append("clickable")
    if elem.get("focusable"):
        status.append("focusable")
    lines.append("| status: {}".format(", ".join(status) if status else "none"))
    lines.append("|")
    lines.append("| XPath:")
    lines.append("|   {}".format(elem.get("xpath", "N/A")))
    lines.append("+" + "-" * 60 + "+")
    return "\n".join(lines)


def print_tree(
    elements: List[Dict[str, Any]],
    filter_text: Optional[str] = None,
    package_name: Optional[str] = None,
) -> None:
    if not elements:
        print("No elements found")
        return

    if filter_text:
        lowered = filter_text.lower()
        elements = [
            elem
            for elem in elements
            if lowered in (elem.get("text", "") or "").lower()
            or lowered in (elem.get("contentDesc", "") or "").lower()
        ]

    print()
    print("=" * 70)
    print("  AIVane ARIA Tree - {} elements".format(len(elements)))
    if package_name:
        print("  Current package: {}".format(package_name))
    print("=" * 70)

    for elem in elements:
        ref_id = elem.get("refId", "?")
        text = elem.get("text", "") or elem.get("contentDesc", "") or "-"
        cls = elem.get("simpleClassName", "")
        x, y = elem.get("x", "?"), elem.get("y", "?")

        flags = []
        if elem.get("clickable"):
            flags.append("click")
        if elem.get("focusable"):
            flags.append("focus")
        flag_str = "[{}]".format(",".join(flags)) if flags else ""
        display_text = text[:25] + "..." if len(str(text)) > 25 else str(text)
        print(
            "  [{:2d}] {:<28} {:<18} ({:4s},{:4s}) {}".format(
                ref_id,
                display_text,
                cls,
                str(x),
                str(y),
                flag_str,
            )
        )

    print("=" * 70)
    print()
