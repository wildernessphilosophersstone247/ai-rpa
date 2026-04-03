from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List


REPO_ROOT = Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the project pre-release verification checks.",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="Recommended release gate: compile Python, run non-device tests, and run device smoke with mutations enabled.",
    )
    parser.add_argument(
        "--device",
        action="store_true",
        help="Run the device smoke suite in addition to the non-device checks.",
    )
    parser.add_argument(
        "--with-mutations",
        action="store_true",
        help="Enable real-device input actions in the device smoke suite.",
    )
    parser.add_argument(
        "--with-screenshot",
        action="store_true",
        help="Enable screenshot verification in the device smoke suite.",
    )
    parser.add_argument(
        "--skip-compile",
        action="store_true",
        help="Skip python -m compileall.",
    )
    parser.add_argument(
        "--skip-non-device",
        action="store_true",
        help="Skip pytest -m \"not device\".",
    )
    return parser.parse_args()


def _run_step(name: str, command: List[str], extra_env: Dict[str, str] | None = None) -> None:
    print()
    print(f"[pre-release] {name}")
    print(f"[pre-release] > {' '.join(command)}")

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    subprocess.run(command, cwd=REPO_ROOT, env=env, check=True)


def _device_env(enable_mutations: bool, enable_screenshot: bool) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if enable_mutations:
        env["AIVANE_E2E_ENABLE_MUTATIONS"] = "1"
    if enable_screenshot:
        env["AIVANE_E2E_ENABLE_SCREENSHOT"] = "1"
    return env


def main() -> int:
    args = _parse_args()

    run_device = args.device or args.release
    enable_mutations = args.with_mutations or args.release
    enable_screenshot = args.with_screenshot

    steps: List[tuple[str, List[str], Dict[str, str] | None]] = []

    if not args.skip_compile:
        steps.append(("Compile Python sources", [sys.executable, "-m", "compileall", "clients/python"], None))

    if not args.skip_non_device:
        steps.append(("Run non-device tests", [sys.executable, "-m", "pytest", "-m", "not device"], None))

    if run_device:
        steps.append(
            (
                "Run device smoke tests",
                [sys.executable, "-m", "pytest", "-m", "device", "-rs"],
                _device_env(enable_mutations=enable_mutations, enable_screenshot=enable_screenshot),
            )
        )

    if not steps:
        print("[pre-release] Nothing to do. Enable at least one check.")
        return 1

    print("[pre-release] Starting checks")
    print(f"[pre-release] Repository: {REPO_ROOT}")

    for name, command, extra_env in steps:
        _run_step(name, command, extra_env=extra_env)

    print()
    print("[pre-release] All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
