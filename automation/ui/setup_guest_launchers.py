# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_DIR = Path.home() / "Desktop"
HOST_REPO_ROOT = Path(r"\\DEV1\D\EDTApps\AI_agent")
STARTUP_DIR = Path(
    os.environ.get(
        "APPDATA",
        str(Path.home() / "AppData" / "Roaming"),
    )
) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def ensure_pywin32() -> None:
    try:
        import win32com.client  # noqa: F401
    except Exception:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pywin32"])


def create_shortcut(shortcut_path: Path, target: str, arguments: str, working_dir: str, icon: str) -> None:
    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(shortcut_path))
    shortcut.TargetPath = target
    shortcut.Arguments = arguments
    shortcut.WorkingDirectory = working_dir
    shortcut.IconLocation = icon
    shortcut.Save()


def create_launchers(autostart: bool, jobs_root: str) -> list[Path]:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    python_target = str(pythonw if pythonw.exists() else Path(sys.executable))
    onec_icon = r"C:\Tools\1cv8\8.5.1.1150\bin\1cv8.exe"
    desktop = DESKTOP_DIR
    startup = STARTUP_DIR

    desktop.mkdir(parents=True, exist_ok=True)
    startup.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []

    ui_shortcut = desktop / "Run AI UI Test.lnk"
    create_shortcut(
        ui_shortcut,
        python_target,
        f'"{HOST_REPO_ROOT / "automation" / "ui" / "run_ui_test_via_vm.py"}"',
        str(HOST_REPO_ROOT),
        python_target,
    )
    created.append(ui_shortcut)

    onec_shortcut = desktop / "1C Russian.lnk"
    create_shortcut(
        onec_shortcut,
        python_target,
        f'"{HOST_REPO_ROOT / "automation" / "ui" / "launch_1c_russian.py"}"',
        str(HOST_REPO_ROOT),
        onec_icon,
    )
    created.append(onec_shortcut)

    if autostart:
        startup_shortcut = startup / "Guest UI Agent.lnk"
        create_shortcut(
            startup_shortcut,
            python_target,
            f'"{HOST_REPO_ROOT / "automation" / "ui" / "guest_ui_agent.py"}" --jobs-root "{jobs_root}"',
            str(HOST_REPO_ROOT),
            python_target,
        )
        created.append(startup_shortcut)

    return created


def main() -> int:
    parser = argparse.ArgumentParser(description="Создание Python-ярлыков для UI-тестов в гостевой Windows VM")
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Создать ярлык автозапуска guest UI agent в Startup",
    )
    parser.add_argument(
        "--jobs-root",
        default=r"\\DEV1\D\EDTApps\AI_agent\automation\logs\vm_ui_jobs",
        help="Каталог jobs, который guest UI agent будет опрашивать",
    )
    args = parser.parse_args()

    os.chdir(REPO_ROOT)
    ensure_pywin32()
    created = create_launchers(args.autostart, args.jobs_root)
    for path in created:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
