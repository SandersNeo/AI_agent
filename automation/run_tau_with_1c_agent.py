# -*- coding: utf-8 -*-
"""
Programmatic Tau-Bench runner that registers the custom 1С-backed agent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _SCRIPT_DIR.parent
_CHEAP_MOCK_TASK_IDS = [
    "create_task_1",
    "create_task_1_with_env_assertions",
    "update_task_1",
    "update_task_with_message_history",
    "update_task_with_initialization_actions",
    "update_task_with_history_and_env_assertions",
    "impossible_task_1",
]

if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT_DIR / ".env")
except ImportError:
    pass

from tau_paths import find_tau_repo  # noqa: E402

_TAU_REPO = find_tau_repo(_ROOT_DIR)
_TAU_SRC = _TAU_REPO / "src"
if str(_TAU_SRC) not in sys.path:
    sys.path.insert(0, str(_TAU_SRC))

from tau2 import TextRunConfig  # noqa: E402
from tau2.evaluator.evaluator import EvaluationType  # noqa: E402
from tau2.registry import registry  # noqa: E402
from tau2.runner import get_tasks, make_run_name  # noqa: E402
from tau2.runner.batch import run_tasks  # noqa: E402
from tau2.utils.utils import DATA_DIR  # noqa: E402

from tau_cheap_user import CheapMockUser  # noqa: E402
from tau2_1c_agent import create_onec_tau_agent  # noqa: E402


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _resolve_cost_mode(args) -> tuple[str, str, list[str] | None, str | None]:
    evaluation_type = args.evaluation_type
    user_name = "user_simulator"
    task_ids = None
    task_split = None

    if args.cost_mode == "free":
        if args.domain != "mock":
            raise ValueError("Режим --cost-mode free сейчас поддерживается только для домена mock.")
        evaluation_type = "all"
        user_name = "cheap_mock_user"
        task_ids = list(_CHEAP_MOCK_TASK_IDS)
    elif args.cost_mode == "cheap" and args.domain == "mock":
        user_name = "cheap_mock_user"
        task_ids = list(_CHEAP_MOCK_TASK_IDS)
        if evaluation_type == "all_with_nl_assertions":
            evaluation_type = "all"
    elif args.cost_mode == "cheap" and args.domain == "telecom":
        if evaluation_type == "all_with_nl_assertions":
            evaluation_type = "all"
        task_split = "small"

    return user_name, evaluation_type, task_ids, task_split


def main() -> int:
    parser = argparse.ArgumentParser(description="Запуск Tau-Bench c 1С-backed custom agent")
    parser.add_argument("--domain", default="mock", choices=["mock", "airline", "retail", "telecom", "banking_knowledge"])
    parser.add_argument("--user-llm", default=os.environ.get("TAU_BENCH_USER_LLM", ""))
    parser.add_argument("--agent-name", default="onec_tau_agent")
    parser.add_argument(
        "--cost-mode",
        default=os.environ.get("TAU_BENCH_COST_MODE", "full"),
        choices=["full", "cheap", "free"],
        help="full = обычный Tau run, cheap = дешёвый mock-контур, free = mock-контур без внешних LLM.",
    )
    parser.add_argument("--num-tasks", type=int, default=int(os.environ.get("TAU_BENCH_NUM_TASKS", "1")))
    parser.add_argument("--num-trials", type=int, default=int(os.environ.get("TAU_BENCH_NUM_TRIALS", "1")))
    parser.add_argument("--task-split", default=os.environ.get("TAU_BENCH_TASK_SPLIT", "base"))
    parser.add_argument("--save-to", default="")
    parser.add_argument("--bridge-config", default=str(_SCRIPT_DIR / "tau_bridge_config.example.json"))
    parser.add_argument("--verbose-logs", action="store_true")
    parser.add_argument(
        "--evaluation-type",
        default="all",
        choices=["all", "all_with_nl_assertions"],
        help="Режим оценки. 'all' отключает LLM judge для nl_assertions.",
    )
    args = parser.parse_args()

    if not _TAU_SRC.exists():
        print("Ошибка: не найден local checkout tau2-bench", file=sys.stderr)
        return 1
    if args.cost_mode != "free" and not args.user_llm:
        print("Ошибка: требуется --user-llm или TAU_BENCH_USER_LLM", file=sys.stderr)
        return 1

    if registry.get_agent_factory(args.agent_name) is None:
        registry.register_agent_factory(create_onec_tau_agent, args.agent_name)
    try:
        registry.get_user_constructor("cheap_mock_user")
    except Exception:
        registry.register_user(CheapMockUser, "cheap_mock_user")

    try:
        user_name, evaluation_type_name, forced_task_ids, forced_task_split = _resolve_cost_mode(args)
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    run_name = args.save_to or f"onec_tau_{args.domain}"
    config = TextRunConfig(
        domain=args.domain,
        agent=args.agent_name,
        user=user_name,
        llm_agent="bridge/1c-agent",
        llm_args_agent={"bridge_config_path": args.bridge_config},
        llm_user=args.user_llm or "deterministic",
        num_tasks=args.num_tasks,
        num_trials=args.num_trials,
        task_split_name=forced_task_split or args.task_split,
        task_ids=forced_task_ids,
        save_to=run_name,
        verbose_logs=args.verbose_logs,
    )

    task_set_name = config.task_set_name or config.domain
    tasks = get_tasks(
        task_set_name=task_set_name,
        task_split_name=config.task_split_name,
        task_ids=config.task_ids,
        num_tasks=config.num_tasks,
    )
    save_dir = DATA_DIR / "simulations" / (config.save_to or make_run_name(config))
    save_path = save_dir / "results.json"
    evaluation_type = (
        EvaluationType.ALL
        if evaluation_type_name == "all"
        else EvaluationType.ALL_WITH_NL_ASSERTIONS
    )
    results = run_tasks(
        config,
        tasks,
        save_path=save_path,
        save_dir=save_dir,
        evaluation_type=evaluation_type,
    )
    summary = {
        "domain": args.domain,
        "agent": args.agent_name,
        "user": user_name,
        "simulations": len(results.simulations),
        "save_to": run_name,
        "evaluation_type": evaluation_type_name,
        "cost_mode": args.cost_mode,
        "task_split": config.task_split_name,
        "task_ids": [task.id for task in tasks],
    }
    _write_json(_SCRIPT_DIR / "logs" / "tau_bench" / f"{run_name}_local_runner_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
