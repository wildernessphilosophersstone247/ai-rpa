#!/usr/bin/env python3
"""
AIVane Android REPL entrypoint.

This is the preferred public-facing command name for the Android REPL beta.
It currently delegates to the compatibility implementation in `aria_tree.py`.
"""

from aria_tree import main


if __name__ == "__main__":
    raise SystemExit(main())
