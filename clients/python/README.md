# Python Clients

This folder contains the public Python-side clients for the first AIVane Android REPL beta.

## Included

- `aivane_repl.py`
  - Preferred public-facing entrypoint for the Android REPL beta
  - Delegates to the current compatibility implementation

- `aria_tree.py`
  - Compatibility client retained for existing flows and older references
  - Supports launcher discovery, UI listing, tap, input, swipe, back, home, screenshot, and related smoke actions

- `run_template_via_api.py`
  - Minimal advanced-path helper for sending a template JSON directly to `/api/execute`
  - Intended for prepared multi-step flows, not the primary first-run story

## Recommended First Use

Start with:

```bash
python aivane_repl.py --repl --url http://<device-ip>:8080
```

`aria_tree.py` remains available as a compatibility entrypoint while the public naming is being cleaned up.

Only move to `run_template_via_api.py` when you already have a stable template file and want deterministic replay.
