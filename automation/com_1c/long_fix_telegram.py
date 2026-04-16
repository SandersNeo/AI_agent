# -*- coding: utf-8 -*-
"""
Совместимый shim: фактическая реализация находится в automation/ops/long_fix_telegram.py.
"""

from pathlib import Path
import sys

_script_dir = Path(__file__).resolve().parent
_repo_root = _script_dir.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from automation.ops.long_fix_telegram import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
