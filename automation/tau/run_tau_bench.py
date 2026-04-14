# -*- coding: utf-8 -*-
"""
Запуск внешнего Tau-Bench рядом с локальным benchmark проекта.

Скрипт не заменяет `test_examples.py`, а добавляет внешний контур оценки:
    - запускает официальный `tau2` CLI из локального checkout tau-bench;
    - сохраняет raw-результат и stdout/stderr в `automation/logs/tau_bench/...`;
    - строит короткое summary;
    - опционально сравнивает внешний результат с локальным `report.json`.

Примеры:
    python automation/tau/run_tau_bench.py --agent-llm gpt-4.1 --user-llm gpt-4.1
    python automation/tau/run_tau_bench.py --domain telecom --num-tasks 25 --num-trials 2
    python automation/tau/run_tau_bench.py --compare-local-report .\\logs\\examples_20260408_090000\\report.json
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _SCRIPT_DIR.parent

if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from tau_paths import find_tau_repo  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT_DIR / ".env")
except ImportError:
    pass


DEFAULT_DOMAINS = ("airline", "retail", "telecom", "mock", "banking_knowledge")


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _extract_numeric(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _iter_simulations(payload):
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return

    if not isinstance(payload, dict):
        return

    for key in ("simulations", "results", "trials", "episodes"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item
            return

    yield payload


def _is_success(simulation: dict) -> bool:
    explicit_keys = ("success", "passed", "solved", "completed")
    for key in explicit_keys:
        value = simulation.get(key)
        if isinstance(value, bool):
            return value

    reward = simulation.get("reward")
    if reward is not None:
        return _extract_numeric(reward, 0) > 0

    score = simulation.get("score")
    if score is not None:
        return _extract_numeric(score, 0) >= 1

    return False


def _sum_tokens(simulation: dict) -> int:
    total = 0
    for key in ("usage_tokens", "total_tokens", "tokens"):
        value = simulation.get(key)
        if value is not None:
            total += int(_extract_numeric(value, 0))

    usage = simulation.get("usage")
    if isinstance(usage, dict):
        for key in ("total_tokens", "prompt_tokens", "completion_tokens"):
            if key in usage:
                total += int(_extract_numeric(usage.get(key), 0))
    return total


def build_summary(raw_payload, meta: dict) -> dict:
    simulations = list(_iter_simulations(raw_payload))
    total = len(simulations)
    passed = sum(1 for item in simulations if _is_success(item))
    rewards = [
        _extract_numeric(item.get("reward"), None)
        for item in simulations
        if item.get("reward") is not None
    ]
    scores = [
        _extract_numeric(item.get("score"), None)
        for item in simulations
        if item.get("score") is not None
    ]
    tokens = sum(_sum_tokens(item) for item in simulations)

    summary = {
        "benchmark": "tau-bench",
        "run_meta": meta,
        "total": total,
        "passed": passed,
        "pass_rate": round((passed / total) * 100, 2) if total else 0,
        "total_tokens": tokens,
        "avg_reward": round(sum(rewards) / len(rewards), 4) if rewards else None,
        "avg_score": round(sum(scores) / len(scores), 4) if scores else None,
        "raw_top_level_keys": sorted(raw_payload.keys()) if isinstance(raw_payload, dict) else [],
    }
    return summary


def build_comparison(tau_summary: dict, local_report: dict) -> dict:
    local_total = int(local_report.get("total") or 0)
    local_passed = int(local_report.get("passed_count") or 0)
    local_avg_score = local_report.get("avg_score")
    return {
        "local_run_id": local_report.get("run_id", ""),
        "local_total": local_total,
        "local_passed": local_passed,
        "local_pass_rate": round((local_passed / local_total) * 100, 2) if local_total else 0,
        "local_avg_score": local_avg_score,
        "tau_total": tau_summary.get("total", 0),
        "tau_passed": tau_summary.get("passed", 0),
        "tau_pass_rate": tau_summary.get("pass_rate", 0),
        "tau_avg_reward": tau_summary.get("avg_reward"),
        "tau_avg_score": tau_summary.get("avg_score"),
    }


def run_command(command: list[str], workdir: Path, env: dict, stdout_path: Path, stderr_path: Path) -> int:
    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
        process = subprocess.run(
            command,
            cwd=str(workdir),
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            check=False,
        )
    return process.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Запуск внешнего Tau-Bench")
    parser.add_argument("--tau-repo", default=None, help="Путь к локальному checkout tau-bench")
    parser.add_argument("--domain", default="airline", choices=DEFAULT_DOMAINS, help="Домен Tau-Bench")
    parser.add_argument("--agent-llm", default=os.environ.get("TAU_BENCH_AGENT_LLM", ""), help="Модель агента")
    parser.add_argument("--user-llm", default=os.environ.get("TAU_BENCH_USER_LLM", ""), help="Модель user simulator")
    parser.add_argument("--num-tasks", type=int, default=int(os.environ.get("TAU_BENCH_NUM_TASKS", "10")), help="Число задач")
    parser.add_argument("--num-trials", type=int, default=int(os.environ.get("TAU_BENCH_NUM_TRIALS", "1")), help="Число прогонов на задачу")
    parser.add_argument("--task-split", default=os.environ.get("TAU_BENCH_TASK_SPLIT", "base"), help="Task split, обычно base")
    parser.add_argument("--run-name", default="", help="Суффикс каталога прогона")
    parser.add_argument("--skip-sync", action="store_true", help="Не выполнять `uv sync` перед запуском")
    parser.add_argument("--compare-local-report", default=None, help="Путь к report.json из test_examples.py")
    parser.add_argument("--extra-arg", action="append", default=[], help="Доп. аргумент для tau2 run; можно указывать несколько раз")
    args = parser.parse_args()

    if not args.agent_llm or not args.user_llm:
        print("Ошибка: укажите --agent-llm и --user-llm либо задайте TAU_BENCH_AGENT_LLM / TAU_BENCH_USER_LLM", file=sys.stderr)
        return 1

    tau_repo = find_tau_repo(_ROOT_DIR, args.tau_repo)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{args.run_name}" if args.run_name else ""
    run_id = f"tau_{args.domain}_{timestamp}{suffix}"
    run_dir = _ensure_dir(_SCRIPT_DIR / "logs" / "tau_bench" / run_id)

    raw_result_path = run_dir / "tau_result.json"
    stdout_path = run_dir / "tau_stdout.txt"
    stderr_path = run_dir / "tau_stderr.txt"
    cmd_path = run_dir / "tau_command.json"
    summary_path = run_dir / "summary.json"
    compare_path = run_dir / "comparison.json"

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    sync_cmd = ["uv", "sync"]
    run_cmd = [
        "uv", "run", "tau2", "run",
        "--domain", args.domain,
        "--agent-llm", args.agent_llm,
        "--user-llm", args.user_llm,
        "--num-trials", str(args.num_trials),
        "--num-tasks", str(args.num_tasks),
        "--task-split", args.task_split,
        "--save-to", str(raw_result_path),
    ]
    for extra in args.extra_arg:
        run_cmd.extend([extra] if extra.startswith("--") and " " not in extra else extra.split())

    _write_json(cmd_path, {
        "tau_repo": str(tau_repo),
        "sync_cmd": sync_cmd,
        "run_cmd": run_cmd,
    })

    if not args.skip_sync:
        print(f"[tau] uv sync @ {tau_repo}")
        sync_rc = run_command(
            sync_cmd,
            workdir=tau_repo,
            env=env,
            stdout_path=run_dir / "uv_sync_stdout.txt",
            stderr_path=run_dir / "uv_sync_stderr.txt",
        )
        if sync_rc != 0:
            print("Ошибка: `uv sync` завершился с ошибкой. Подробности в automation/logs/tau_bench/...", file=sys.stderr)
            return sync_rc

    print(f"[tau] run_id={run_id}")
    print(f"[tau] domain={args.domain} tasks={args.num_tasks} trials={args.num_trials}")
    rc = run_command(run_cmd, workdir=tau_repo, env=env, stdout_path=stdout_path, stderr_path=stderr_path)
    if rc != 0:
        print("Ошибка: `tau2 run` завершился с ошибкой. См. tau_stderr.txt", file=sys.stderr)
        return rc

    if not raw_result_path.exists():
        print("Ошибка: tau2 завершился без ожидаемого файла результата", file=sys.stderr)
        return 1

    raw_payload = _read_json(raw_result_path)
    summary = build_summary(raw_payload, {
        "run_id": run_id,
        "tau_repo": str(tau_repo),
        "domain": args.domain,
        "agent_llm": args.agent_llm,
        "user_llm": args.user_llm,
        "num_tasks": args.num_tasks,
        "num_trials": args.num_trials,
        "task_split": args.task_split,
    })
    _write_json(summary_path, summary)

    print(f"[tau] pass_rate={summary['pass_rate']}% ({summary['passed']}/{summary['total']})")
    if summary.get("avg_reward") is not None:
        print(f"[tau] avg_reward={summary['avg_reward']}")
    if summary.get("avg_score") is not None:
        print(f"[tau] avg_score={summary['avg_score']}")
    if summary.get("total_tokens"):
        print(f"[tau] total_tokens={summary['total_tokens']}")
    print(f"[tau] artifacts={run_dir}")

    if args.compare_local_report:
        local_report = _read_json(Path(args.compare_local_report))
        comparison = build_comparison(summary, local_report)
        _write_json(compare_path, comparison)
        print(
            "[compare] "
            f"local_pass_rate={comparison['local_pass_rate']}% "
            f"vs tau_pass_rate={comparison['tau_pass_rate']}%"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
