# Agent Examples — Android REPL Beta

These prompt snippets show how Codex, Claude Code, or OpenClaw can call the AIVane Android REPL via the public `aivane_repl.py` entrypoint.

## Codex (plain CLI)

```
Use the AIVane Android REPL client at `clients/python/aivane_repl.py`.
1. Run `python aivane_repl.py --repl --url http://<device-ip>:8080`.
2. Save the URL (`set url http://<device-ip>:8080`).
3. Use `apps`, `la com.xingin.xhs`, `list`, `tap 127`, `input 3 "hello"`, `back`, `press home`.
4. Request `screenshot` if MediaProjection permission is granted.
```

## Claude Code (structured guidance)

```
Goal: Open the AIVane app, find the “健康” card, tap it, then return home.
Steps:
- `set url` (if needed)
- `health`
- `apps` -> confirm com.xiaomi.weather2
- `la com.xiaomi.weather2`
- `list` -> take note of refId for “健康”
- `tap <refId>`
- `back`
- `press home`
```

## OpenClaw (tool-invocation)

```
Tool: aivane_repl
Inputs:
  - command: ["--launch", "com.xingin.xhs"]
  - command: ["--list"]
  - command: ["--tap", "127"]
  - command: ["--input", "3", "你好"]
```

Each agent can expand on these snippets with more specific selectors, loops, or input strings once a stable ARIA tree snapshot is available.
