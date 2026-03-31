See the Chinese overview at [README_CN.md](README_CN.md).

# AIVane AI RPA

This repository represents the public-facing `aivane.net` launch for the `aivanelabs/ai-rpa` project. Under the AIVane umbrella ("AI Mobile Automation"), we start with a transparent Android REPL beta that lets AI agents explore UI trees and drive Android devices through a lightweight Python CLI.

## Quick Start

1. Ensure your Android device has the AIVane REPL beta APK installed and is reachable over Wi‑Fi.
2. Run the CLI:  
   ```bash
   python clients/python/aivane_repl.py --repl --url http://<device-ip>:8080
   ```
3. Inside the REPL, save the URL (`set url http://<device-ip>:8080`) and run the smoke path: `health`, `apps`, `la <package>`, `list`, `tap <refId>`, `input <refId>`, `back`, `press home`, `screenshot`.

## Public Assets

- `clients/python/aivane_repl.py`: preferred public-facing REPL entrypoint for Android device control.
- `clients/python/aria_tree.py`: compatibility client that currently powers the same flow while older references are updated.
- `docs/`: quickstart, protocol, permissions, known limitations, feedback, release notes, and repo scope.
- `examples/`: smoke flows and minimal usage examples.
- `skills/android-repl/`: sample skill definition with prompts and agent metadata.

## Installation & Launch

- `docs/install-android-repl.md`: steps to install the APK, ensure LAN connectivity, and run the first smoke.
- `examples/start-app-repl.sh`: a public-friendly starter script to connect to a device, optionally install the APK, and launch the Android REPL service.

## Additional Resources

- `docs/agent-examples.md`: starter prompts and usage snippets for Codex / Claude Code / OpenClaw.
- `.github/ISSUE_TEMPLATE/`: bug and feature report templates to capture actionable information from early users.

## Known Limitations

See `docs/known-limitations.md` for the current Beta boundaries (permission prompts, LAN-only use, and other beta limits). These limitations reflect the state of the remote Android runtime and the permissions it can request today.

## Contact

For questions and light coordination, please email `aivanelabs@gmail.com`.
