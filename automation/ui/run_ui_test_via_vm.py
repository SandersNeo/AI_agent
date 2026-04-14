# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOST_JOBS_ROOT = REPO_ROOT / "automation" / "logs" / "vm_ui_jobs"
DEFAULT_GUEST_JOBS_ROOT = r"H:\EDTApps\AI_agent\automation\logs\vm_ui_jobs"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_job(args: argparse.Namespace, job_id: str, run_dir: Path) -> dict[str, object]:
    return {
        "job_id": job_id,
        "created_at_local": datetime.now().isoformat(),
        "platform_exe": args.platform_exe,
        "base_path": args.base_path,
        "user": args.user,
        "prompt": args.prompt,
        "expected_text": args.expected_text,
        "timeout_sec": args.timeout_sec,
        "startup_timeout_sec": args.startup_timeout_sec,
        "backend": args.backend,
        "leave_open": args.leave_open,
        "run_dir": str(run_dir),
        "log_file": str(run_dir / "ui_test.log"),
        "screenshot_dir": str(run_dir / "artifacts"),
    }


def wait_for_result(host_jobs_root: Path, job_id: str, timeout_sec: int) -> Path:
    completed = host_jobs_root / "completed" / f"{job_id}.json"
    failed = host_jobs_root / "failed" / f"{job_id}.json"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if completed.exists():
            return completed
        if failed.exists():
            return failed
        time.sleep(2)
    raise TimeoutError(f"Не дождались завершения VM UI job {job_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Запуск UI-теста 1С через гостевого VM-агента")
    parser.add_argument("--prompt", default="какие поля есть у справочника Контрагенты")
    parser.add_argument("--expected-text", default="Поля успешно получены")
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--startup-timeout-sec", type=int, default=120)
    parser.add_argument("--backend", default="uia", choices=["uia", "win32"])
    parser.add_argument("--platform-exe", default=r"C:\Tools\1cv8\8.5.1.1150\bin\1cv8.exe")
    parser.add_argument("--base-path", default=r"\\DEV1\AIBase$")
    parser.add_argument("--user", default="Администратор")
    parser.add_argument("--leave-open", action="store_true")
    parser.add_argument("--wait-timeout-sec", type=int, default=600)
    parser.add_argument("--host-jobs-root", default=str(DEFAULT_HOST_JOBS_ROOT))
    parser.add_argument("--guest-jobs-root", default=DEFAULT_GUEST_JOBS_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    host_jobs_root = ensure_dir(Path(args.host_jobs_root))
    ensure_dir(host_jobs_root / "pending")
    ensure_dir(host_jobs_root / "running")
    ensure_dir(host_jobs_root / "completed")
    ensure_dir(host_jobs_root / "failed")
    ensure_dir(host_jobs_root / "runs")

    job_id = f"{timestamp()}_{uuid.uuid4().hex[:8]}"
    guest_run_dir = Path(args.guest_jobs_root) / "runs" / job_id
    job = build_job(args, job_id, guest_run_dir)
    pending_job_path = host_jobs_root / "pending" / f"{job_id}.json"
    pending_job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"VM UI job queued: {job_id}")
    print(f"Pending file: {pending_job_path}")
    print("Waiting for guest agent...")

    try:
        result_path = wait_for_result(host_jobs_root, job_id, args.wait_timeout_sec)
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        print(f"Host jobs root: {host_jobs_root}", file=sys.stderr)
        return 2

    result = json.loads(result_path.read_text(encoding="utf-8"))
    print(f"Result file: {result_path}")
    print(f"Status: {result.get('status')}")
    print(f"Exit code: {result.get('exit_code')}")
    print(f"Log file: {result.get('log_file')}")
    print(f"Artifacts dir: {result.get('screenshot_dir')}")
    if result.get("artifacts"):
        print("Artifacts:")
        for artifact in result["artifacts"]:
            print(f"  {artifact}")
    return int(result.get("exit_code", 1))


if __name__ == "__main__":
    raise SystemExit(main())
