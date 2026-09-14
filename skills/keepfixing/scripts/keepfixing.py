#!/usr/bin/env python3
"""Restricted companion entrypoint that resolves the shared keepgoing runtime."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def runtime_script_dir() -> Path:
    configured = os.environ.get("KEEPGOING_SKILL_HOME")
    if configured:
        candidate = Path(configured).expanduser().resolve() / "scripts"
    else:
        candidate = Path(__file__).resolve().parents[2] / "keepgoing" / "scripts"
    if not (candidate / "keepgoing_runtime" / "cli.py").is_file():
        raise RuntimeError(
            "The sibling keepgoing skill is required; install keepgoing and keepfixing together"
        )
    return candidate


SCRIPT_DIR = runtime_script_dir()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from keepgoing_runtime.cli import main


if __name__ == "__main__":
    raise SystemExit(main(mode="keepfixing"))
