# -*- coding: utf-8 -*-
"""
Shared path helpers for the local Tau-Bench checkout.
"""

from __future__ import annotations

import os
from pathlib import Path


def find_tau_repo(root_dir: Path, explicit_path: str | None = None) -> Path:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))

    env_path = os.environ.get("TAU_BENCH_REPO")
    if env_path:
        candidates.append(Path(env_path))

    candidates.extend(
        [
            root_dir / "vendor" / "tau2-bench",
            root_dir / "temp" / "tau2-bench",
            root_dir.parent / "tau2-bench",
        ]
    )

    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "pyproject.toml").exists() and (resolved / "README.md").exists():
            return resolved

    raise FileNotFoundError(
        "Не найден локальный checkout tau-bench. "
        "Укажите --tau-repo или TAU_BENCH_REPO."
    )
