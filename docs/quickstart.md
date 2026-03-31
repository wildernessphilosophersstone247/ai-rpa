# Quickstart Draft — AIVane Android REPL

This quickstart introduces the publicly staged CLI for AIVane (AI Mobile Automation) under `aivanelabs/ai-rpa` on `aivane.net`.

## What You Need

- An Android device with the AIVane REPL beta APK installed
- A desktop or laptop on the same LAN
- Python 3.7+

## First Run

Run the CLI with an explicit URL:

```bash
python clients/python/aria_tree.py --repl --url http://<device-ip>:8080
```

Inside the REPL, save the URL for later:

```text
set url http://<device-ip>:8080
```

## Minimal Smoke Flow

1. Check health:

```bash
curl http://<device-ip>:8080/health
```

2. List launchable apps:

```bash
python clients/python/aria_tree.py --apps --url http://<device-ip>:8080
```

3. Launch an app:

```bash
python clients/python/aria_tree.py --launch <package> --url http://<device-ip>:8080
```

4. Inspect the current screen:

```bash
python clients/python/aria_tree.py --list --url http://<device-ip>:8080
```

5. Interact:

```bash
python clients/python/aria_tree.py --tap <refId> --url http://<device-ip>:8080
python clients/python/aria_tree.py --input <refId> "hello" --url http://<device-ip>:8080
python clients/python/aria_tree.py --back --url http://<device-ip>:8080
```

## Draft Notes

- `/api/execute` remains available for advanced multi-step templates.
- The public protocol may be narrowed and cleaned up before release.
- Public sample skills are not staged yet.
