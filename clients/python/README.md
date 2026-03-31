# Python Clients

This folder contains the public Python-side clients for the first AIVane Android REPL beta.

## Included

- `aria_tree.py`
  - REPL-first Android control client
  - Supports launcher discovery, UI listing, tap, input, swipe, back, home, screenshot, and related smoke actions

- `run_template_via_api.py`
  - Minimal advanced-path helper for sending a template JSON directly to `/api/execute`
  - Intended for prepared multi-step flows, not the primary first-run story

## Recommended First Use

Start with:

```bash
python aria_tree.py --repl --url http://<device-ip>:8080
```

Only move to `run_template_via_api.py` when you already have a stable template file and want deterministic replay.

