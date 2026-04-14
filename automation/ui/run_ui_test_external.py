# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    os.chdir(REPO_ROOT)
    cmd = [
        sys.executable,
        "-u",
        str(REPO_ROOT / "automation" / "ui" / "ui_1c_agent_test.py"),
        *sys.argv[1:],
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    process = subprocess.Popen(cmd, cwd=REPO_ROOT, creationflags=creationflags)
    return 0 if process.pid else 1


if __name__ == "__main__":
    raise SystemExit(main())
