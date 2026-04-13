# -*- coding: utf-8 -*-
"""
Обновляет конфигурацию БД и запускает Vanessa Automation с указанным feature-файлом.

Примеры:
    python automation/vanessa/update_and_run_vanessa.py
    python automation/vanessa/update_and_run_vanessa.py --feature-file automation/vanessa/TestAIAgent.feature
    python automation/vanessa/update_and_run_vanessa.py --skip-db-update --install-vaextension
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
AUTOMATION_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = AUTOMATION_DIR.parent

if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))

from com_1c.com_connector import disable_proxy_env_for_1c, setup_console_encoding
from com_1c.config import get_connection_string, get_platform_85


FINISHED_MARKER = "Выполнение сценариев закончено."
SUCCESS_MARKER = "Выполнение сценариев закончено. Ошибок не было."
DEFAULT_CONNECTION_STRING = 'File="D:\\EDT_base\\КонфигурацияТест";'
EXTENSION_NAME = "ИИ_Агент"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Обновить БД 1С и запустить Vanessa Automation с указанным feature."
    )
    parser.add_argument(
        "--platform-exe",
        default=get_platform_85(),
        help="Путь к 1cv8.exe. По умолчанию используется PLATFORM_85 из .env/env.",
    )
    parser.add_argument(
        "--connection-string",
        default=None,
        help="Строка подключения к базе 1С. По умолчанию берётся из 1C_CONNECTION_STRING.",
    )
    parser.add_argument("--user-name", default="", help="Пользователь 1С.")
    parser.add_argument("--password", default="", help="Пароль 1С.")
    parser.add_argument(
        "--log-dir",
        default=str(SCRIPT_DIR / "logs"),
        help="Каталог логов Vanessa/обновления БД.",
    )
    parser.add_argument(
        "--vanessa-runner-epf",
        default=str(SCRIPT_DIR / "vanessa-automation-single.epf"),
        help="Путь к Vanessa Automation .epf.",
    )
    parser.add_argument(
        "--vaextension-cfe",
        default=str(SCRIPT_DIR / "VAExtension.cfe"),
        help="Путь к VAExtension.cfe.",
    )
    parser.add_argument(
        "--feature-file",
        default=str(SCRIPT_DIR / "TestAIAgent.feature"),
        help="Путь к feature-файлу Vanessa.",
    )
    parser.add_argument(
        "--vaparams-path",
        default=str(SCRIPT_DIR / "VAParams.json"),
        help="Путь к VAParams.json.",
    )
    parser.add_argument(
        "--skip-db-update",
        action="store_true",
        help="Не выполнять UpdateDBCfg перед запуском Vanessa.",
    )
    parser.add_argument(
        "--skip-build-from-xml",
        action="store_true",
        help="Не загружать текущее расширение из xml/ перед UpdateDBCfg.",
    )
    parser.add_argument(
        "--xml-path",
        default=str(PROJECT_ROOT / "xml"),
        help="Путь к XML-выгрузке расширения.",
    )
    parser.add_argument(
        "--install-vaextension",
        action="store_true",
        help="Скачать при необходимости и загрузить VAExtension.cfe в базу.",
    )
    parser.add_argument(
        "--install-vanessa-ext",
        action="store_true",
        help="Тихо установить VanessaExt через runner EPF.",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=15,
        help="Таймаут ожидания завершения сценариев Vanessa.",
    )
    return parser.parse_args()


def ensure_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Файл {description} не найден: {path}")


def run_1cv8(platform_exe: Path, arguments: list[str], operation_name: str, wait: bool = True) -> subprocess.Popen | int:
    print(f"==> {operation_name}")
    print("    1cv8.exe", " ".join(arguments))
    cwd = str(platform_exe.parent)
    if wait:
        completed = subprocess.run([str(platform_exe), *arguments], cwd=cwd, check=False)
        if completed.returncode != 0:
            raise RuntimeError(
                f"Команда 1cv8 для операции '{operation_name}' завершилась с кодом {completed.returncode}"
            )
        return completed.returncode
    return subprocess.Popen([str(platform_exe), *arguments], cwd=cwd)


def build_auth_args(user_name: str, password: str) -> list[str]:
    args: list[str] = []
    if user_name.strip():
        args.extend(["/N", user_name])
    if password != "":
        args.extend(["/P", password])
    return args


def parse_file_connection_string(connection_string: str) -> tuple[str | None, str, str]:
    if not connection_string.strip().lower().startswith("file="):
        return None, "", ""

    match_path = re.search(r'file\s*=\s*"([^"]+)"', connection_string, re.IGNORECASE)
    match_user = re.search(r'usr\s*=\s*"([^"]*)"', connection_string, re.IGNORECASE)
    match_pwd = re.search(r'pwd\s*=\s*"?([^";]*)"?', connection_string, re.IGNORECASE)

    ib_path = match_path.group(1).strip().rstrip("\\") if match_path else None
    ib_user = match_user.group(1) if match_user else ""
    ib_pwd = match_pwd.group(1) if match_pwd else ""
    return ib_path, ib_user, ib_pwd


def build_connection_args(connection_string: str, user_name: str, password: str) -> list[str]:
    ib_path, parsed_user, parsed_pwd = parse_file_connection_string(connection_string)
    effective_user = user_name if user_name.strip() else parsed_user
    effective_pwd = password if password != "" else parsed_pwd

    if ib_path:
        return ["/F", ib_path, *build_auth_args(effective_user, effective_pwd)]

    return ["/IBConnectionString", connection_string, *build_auth_args(user_name, password)]


def initialize_vaparams_file(path: Path, feature_file_path: Path, connection_string: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Lang": "ru",
        "featurepath": str(feature_file_path),
        "ВыполнитьСценарии": True,
        "useaddin": True,
        "TestClient": {
            "runtestclientwithmaximizedwindow": True,
            "datatestclients": [
                {
                    "Name": "LocalFileBase",
                    "PathToInfobase": connection_string,
                    "PortTestClient": 48010,
                    "AddItionalParameters": "",
                    "ClientType": "Thin",
                    "ComputerName": "localhost",
                }
            ],
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_vaparams(path: Path, feature_file_path: Path, connection_string: str) -> dict:
    if not path.exists():
        print(f"Создаю файл VAParams.json по умолчанию: {path}")
        initialize_vaparams_file(path, feature_file_path, connection_string)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Не удалось прочитать VAParams.json: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Не удалось загрузить структуру настроек из VAParams.json")

    payload["featurepath"] = str(feature_file_path)
    payload["ВыполнитьСценарии"] = True
    payload["useaddin"] = True

    test_client = payload.setdefault("TestClient", {})
    test_client["runtestclientwithmaximizedwindow"] = True
    test_client["datatestclients"] = [
        {
            "Name": "LocalFileBase",
            "PathToInfobase": connection_string,
            "PortTestClient": 48010,
            "AddItionalParameters": "",
            "ClientType": "Thin",
            "ComputerName": "localhost",
        }
    ]

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def fetch_latest_vaextension_url() -> str:
    request = urllib.request.Request(
        "https://api.github.com/repos/Pr-Mex/vanessa-automation/releases/latest",
        headers={"User-Agent": "Codex"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.loads(response.read().decode("utf-8"))

    for asset in release.get("assets", []):
        name = str(asset.get("name", ""))
        if name.startswith("VAExtension") and name.endswith(".cfe"):
            return str(asset["browser_download_url"])

    raise RuntimeError("Не найден asset VAExtension*.cfe в latest release vanessa-automation.")


def ensure_vaextension_cfe(target_path: Path) -> None:
    if target_path.is_file():
        return

    target_path.parent.mkdir(parents=True, exist_ok=True)
    print("==> Скачивание VAExtension.cfe")
    download_url = fetch_latest_vaextension_url()
    request = urllib.request.Request(download_url, headers={"User-Agent": "Codex"})
    with urllib.request.urlopen(request, timeout=120) as response:
        target_path.write_bytes(response.read())


def install_vaextension_in_database(
    platform_exe: Path,
    cfe_path: Path,
    connection_string: str,
    user_name: str,
    password: str,
    log_path: Path,
) -> None:
    base_args = [
        "DESIGNER",
        "/DisableStartupDialogs",
        "/DisableStartupMessages",
        *build_connection_args(connection_string, user_name, password),
    ]

    load_args = [*base_args, "/Out", str(log_path), "/LoadCfg", str(cfe_path), "-Extension", "VAExtension"]
    run_1cv8(platform_exe, load_args, "Загрузка расширения VAExtension в конфигурацию")

    update_args = [*base_args, "/Out", str(log_path), "/UpdateDBCfg", "-Extension", "VAExtension"]
    run_1cv8(platform_exe, update_args, "Обновление БД для расширения VAExtension")


def install_vanessa_ext_quietly(
    platform_exe: Path,
    runner_path: Path,
    connection_string: str,
    user_name: str,
    password: str,
    log_path: Path,
) -> None:
    args = [
        "ENTERPRISE",
        "/DisableStartupDialogs",
        "/DisableStartupMessages",
        "/TESTMANAGER",
        *build_connection_args(connection_string, user_name, password),
        "/Execute",
        str(runner_path),
        "/Out",
        str(log_path),
        "/C",
        "QuietInstallVanessaExtAndClose=1",
    ]
    run_1cv8(platform_exe, args, "Тихая установка VanessaExt")


def iter_processes_wmic() -> list[dict[str, str]]:
    if shutil.which("wmic") is None:
        return []
    completed = subprocess.run(
        ["wmic", "process", "get", "ProcessId,Name,CommandLine", "/format:csv"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return []

    rows: list[dict[str, str]] = []
    for row in csv.DictReader(completed.stdout.splitlines()):
        if not row:
            continue
        rows.append({key: (value or "") for key, value in row.items()})
    return rows


def iter_processes_powershell() -> list[dict[str, str]]:
    if shutil.which("pwsh") is None:
        return []

    command = (
        "Get-CimInstance Win32_Process | "
        "Select-Object Name,ProcessId,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        payload = [payload]

    rows: list[dict[str, str]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "Name": str(row.get("Name", "") or ""),
                "ProcessId": str(row.get("ProcessId", "") or ""),
                "CommandLine": str(row.get("CommandLine", "") or ""),
            }
        )
    return rows


def iter_processes() -> list[dict[str, str]]:
    rows = iter_processes_wmic()
    if rows:
        return rows
    return iter_processes_powershell()


def read_text_with_fallbacks(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "cp1251", "utf-16"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def stop_vanessa_test_processes(runner_path: Path) -> None:
    try:
        if shutil.which("pwsh") is not None:
            runner_escaped = str(runner_path).replace("'", "''")
            ps_script = f"""
$runner = '{runner_escaped}'.ToLower()
$targets = Get-CimInstance Win32_Process | Where-Object {{
    $_.Name -like '1cv8*.exe' -and $_.CommandLine -and (
        $_.CommandLine.ToLower().Contains('/testclient') -or
        $_.CommandLine.ToLower().Contains('/testmanager') -or
        $_.CommandLine.ToLower().Contains($runner)
    )
}}
foreach ($p in $targets) {{
    try {{
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
    }} catch {{
    }}
}}
"""
            subprocess.run(
                ["pwsh", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            time.sleep(1)

        runner_str = str(runner_path).lower()
        targets: list[str] = []
        for process in iter_processes():
            name = process.get("Name", "").lower()
            cmdline = process.get("CommandLine", "").lower()
            pid = process.get("ProcessId", "").strip()
            if not pid or not name.startswith("1cv8"):
                continue
            if "/testclient" in cmdline or "/testmanager" in cmdline or (runner_str and runner_str in cmdline):
                targets.append(pid)

        for pid in targets:
            subprocess.run(
                ["taskkill", "/PID", pid, "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
    except Exception as exc:
        print(f"Предупреждение: не удалось завершить тестовые процессы 1С: {exc}")


def invoke_vanessa_feature_run(
    platform_exe: Path,
    arguments: list[str],
    operation_name: str,
    log_path: Path,
    runner_path: Path,
    timeout_minutes: int,
) -> None:
    print(f"==> {operation_name}")
    print("    1cv8.exe", " ".join(arguments))

    stop_vanessa_test_processes(runner_path)
    if log_path.exists():
        try:
            log_path.unlink()
        except OSError:
            pass

    process = subprocess.Popen([str(platform_exe), *arguments], cwd=str(platform_exe.parent))
    deadline = time.time() + timeout_minutes * 60
    saw_finished_marker = False
    saw_success_marker = False

    try:
        while time.time() < deadline:
            time.sleep(2)

            if process.poll() is not None:
                break

            if log_path.exists():
                try:
                    content = read_text_with_fallbacks(log_path)
                except Exception:
                    content = ""
                if FINISHED_MARKER in content:
                    saw_finished_marker = True
                    saw_success_marker = SUCCESS_MARKER in content
                    stop_vanessa_test_processes(runner_path)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        pass
                    break

        if process.poll() is None:
            stop_vanessa_test_processes(runner_path)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError("Превышено время ожидания завершения Vanessa Automation.") from exc

        if process.returncode != 0 and not (saw_finished_marker and saw_success_marker):
            raise RuntimeError(
                f"Команда 1cv8 для операции '{operation_name}' завершилась с кодом {process.returncode}"
            )
    finally:
        stop_vanessa_test_processes(runner_path)


def main() -> int:
    setup_console_encoding()
    disable_proxy_env_for_1c()
    args = parse_args()

    platform_exe = Path(args.platform_exe).expanduser().resolve()
    connection_string = get_connection_string(args.connection_string) or DEFAULT_CONNECTION_STRING
    os.environ["1C_CONNECTION_STRING"] = connection_string

    feature_file = Path(args.feature_file).expanduser().resolve()
    runner_epf = Path(args.vanessa_runner_epf).expanduser().resolve()
    vaextension_cfe = Path(args.vaextension_cfe).expanduser().resolve()
    vaparams_path = Path(args.vaparams_path).expanduser().resolve()
    log_dir = Path(args.log_dir).expanduser().resolve()
    xml_path = Path(args.xml_path).expanduser().resolve()

    ensure_file(platform_exe, "платформы 1cv8")
    ensure_file(runner_epf, "Vanessa Automation (epf)")
    ensure_file(feature_file, "Vanessa Automation feature")
    if not args.skip_build_from_xml and not xml_path.is_dir():
        raise FileNotFoundError(f"Каталог XML-выгрузки не найден: {xml_path}")

    load_vaparams(vaparams_path, feature_file, connection_string)
    log_dir.mkdir(parents=True, exist_ok=True)

    update_log = log_dir / "update-db.log"
    build_load_log = log_dir / "build-load.log"
    vanessa_log = log_dir / "vanessa.log"
    install_ext_log = log_dir / "install-vanessa-ext.log"
    install_vaextension_log = log_dir / "install-vaextension.log"

    if not args.skip_build_from_xml:
        load_args = [
            "DESIGNER",
            "/DisableStartupDialogs",
            "/DisableStartupMessages",
            *build_connection_args(connection_string, args.user_name, args.password),
            "/Out",
            str(build_load_log),
            "/LoadConfigFromFiles",
            str(xml_path),
            "-Extension",
            EXTENSION_NAME,
        ]
        run_1cv8(platform_exe, load_args, "Загрузка xml в конфигурацию")
    else:
        print("Пропускаю загрузку расширения из xml (флаг --skip-build-from-xml).")

    if not args.skip_db_update:
        designer_args = [
            "DESIGNER",
            "/DisableStartupDialogs",
            "/DisableStartupMessages",
            *build_connection_args(connection_string, args.user_name, args.password),
            "/Out",
            str(update_log),
            "/UpdateDBCfg",
            "-Extension",
            EXTENSION_NAME,
        ]
        run_1cv8(platform_exe, designer_args, "Обновление конфигурации БД")
    else:
        print("Пропускаю обновление БД (флаг --skip-db-update).")

    if args.install_vaextension:
        ensure_vaextension_cfe(vaextension_cfe)
        install_vaextension_in_database(
            platform_exe,
            vaextension_cfe,
            connection_string,
            args.user_name,
            args.password,
            install_vaextension_log,
        )

    if args.install_vanessa_ext:
        install_vanessa_ext_quietly(
            platform_exe,
            runner_epf,
            connection_string,
            args.user_name,
            args.password,
            install_ext_log,
        )

    vanessa_command = (
        f"StartFeaturePlayer;FeatureFile={feature_file};CloseTestClientBefore=1;StopOnError=1;"
        f"ShowMainForm=0;LogDirectory={log_dir};VAParams={vaparams_path};vanessarun=1;"
    )
    vanessa_args = [
        "ENTERPRISE",
        "/DisableStartupDialogs",
        "/DisableStartupMessages",
        "/TESTMANAGER",
        *build_connection_args(connection_string, args.user_name, args.password),
        "/Execute",
        str(runner_epf),
        "/Out",
        str(vanessa_log),
        "/C",
        vanessa_command,
    ]

    invoke_vanessa_feature_run(
        platform_exe,
        vanessa_args,
        "Запуск сценария Vanessa Automation",
        vanessa_log,
        runner_epf,
        args.timeout_minutes,
    )
    print("Выполнение завершено: обновление БД и сценарий Vanessa успешно отработали.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise SystemExit(1)
