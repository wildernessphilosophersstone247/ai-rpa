# Agent Examples — Android REPL Beta

These prompt snippets show how Codex, Claude Code, or OpenClaw can call the agent-android via the public `agent-android.py` entrypoint.

## Codex (plain CLI)

```
Use the agent-android client at `clients/python/agent-android.py`.
1. Run `python agent-android.py --repl --url http://<device-ip>:8080`.
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
Tool: agent-android
Inputs:
  - command: ["--launch", "com.xingin.xhs"]
  - command: ["--list"]
  - command: ["--tap", "127"]
  - command: ["--input", "3", "你好"]
```

Each agent can expand on these snippets with more specific selectors, loops, or input strings once a stable ARIA tree snapshot is available.


