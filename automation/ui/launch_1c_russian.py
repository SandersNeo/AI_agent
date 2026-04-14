# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ONEC_EXE = Path(r"C:\Tools\1cv8\8.5.1.1150\bin\1cv8.exe")


def main() -> int:
    os.chdir(REPO_ROOT)
    cmd = [str(ONEC_EXE), "/L", "ru"]
    process = subprocess.Popen(cmd, cwd=ONEC_EXE.parent)
    return int(process.pid > 0)


if __name__ == "__main__":
    raise SystemExit(main())
