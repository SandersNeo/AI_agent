# Tau-Bench

В репозиторий добавлен отдельный внешний контур оценки через официальный `tau2` CLI. Он нужен не вместо локального benchmark, а рядом с ним:

- `automation/tau/test_examples.py` остаётся основным KPI для сценариев 1С;
- `automation/tau/run_tau_bench.py` даёт внешний референс на публичном benchmark;
- результаты нужно читать раздельно, не сливая в один score.

## Что даёт интеграция

- Внешнюю точку сравнения для tool-using agent.
- Проверку многошагового диалога и policy-following вне ваших локальных сценариев.
- Отдельные артефакты прогона в `automation/logs/tau_bench/...`.
- Базовое сравнение с `report.json` из `test_examples.py`.

## Ограничения

- Tau-Bench доменно ориентирован на customer-service сценарии (`airline`, `retail`, `telecom` и др.).
- Ваш агент работает в среде 1С, поэтому Tau-Bench не заменяет локальные end-to-end сценарии.
- На первом этапе интеграция запускает официальный benchmark как внешний контур по модели/провайдеру. Полный прогон именно вашего 1С-агента внутри Tau-Bench потребует отдельного adapter/bridge слоя.

## Предварительная настройка

1. Клонируйте репозиторий Tau-Bench локально.
2. Установите `uv`.
3. Задайте путь к checkout через `TAU_BENCH_REPO` в `.env` или аргумент `--tau-repo`.
4. Убедитесь, что в окружении доступны ключи провайдера, который использует Tau-Bench.

Пример:

```powershell
git clone https://github.com/sierra-research/tau2-bench .\vendor\tau2-bench
```

## Быстрый запуск

Из корня репозитория:

```powershell
python automation\tau\run_tau_bench.py --agent-llm gpt-4.1 --user-llm gpt-4.1
python automation\tau\run_tau_bench.py --domain telecom --num-tasks 25 --num-trials 2
python automation\tau\run_tau_bench.py --compare-local-report .\logs\examples_20260408_090000\report.json
```

Для запуска именно вашего 1С-backed custom agent используйте:

```powershell
cd vendor\tau2-bench
uv run python ..\..\automation\tau\run_tau_with_1c_agent.py --domain mock --user-llm gpt-4o --evaluation-type all
uv run python ..\..\automation\tau\run_tau_with_1c_agent.py --domain mock --user-llm gpt-4o --evaluation-type all_with_nl_assertions
```

## Режимы стоимости

У `run_tau_with_1c_agent.py` теперь есть 3 режима:

- `full`: обычный Tau-Bench run с LLM user simulator и выбранным evaluation mode.
- `cheap`: дешёвый режим. Для `mock` использует deterministic user и отключает `nl_assertions`.
- `cheap` для `telecom`: использует `small` split и отключает `nl_assertions`.
- `free`: бесплатный режим для `mock`. Не использует внешний LLM вообще.

Примеры:

```powershell
cd vendor\tau2-bench
uv run python ..\..\automation\tau\run_tau_with_1c_agent.py --domain mock --cost-mode free --num-tasks 7 --num-trials 1
uv run python ..\..\automation\tau\run_tau_with_1c_agent.py --domain mock --cost-mode cheap --num-tasks 7 --num-trials 1
uv run python ..\..\automation\tau\run_tau_with_1c_agent.py --domain telecom --cost-mode cheap --user-llm gpt-4o --num-tasks 1
uv run python ..\..\automation\tau\run_tau_with_1c_agent.py --domain telecom --cost-mode full --user-llm gpt-4o --evaluation-type all
```

Что важно:

- `free` сейчас поддерживается только для `mock`.
- `cheap` для `telecom` всё равно тратит реальные токены user simulator, просто заметно меньше за счёт `small` split и отключённого NL judge.
- `cheap/free` нужны для smoke/regression контура, а не для публично сопоставимого leaderboard-style результата.
- в `free` используется фиксированный стабильный поднабор `mock` задач без внешнего LLM.

Что делает скрипт:

- при необходимости выполняет `uv sync` в checkout Tau-Bench;
- запускает `uv run tau2 run ... --save-to ...`;
- сохраняет:
  - `tau_result.json`
  - `summary.json`
  - `tau_stdout.txt`
  - `tau_stderr.txt`
  - `comparison.json` при сравнении с локальным отчётом.

## Как читать результаты

Смотрите на два независимых контура:

- Локальный: `passed_count/total`, `avg_score`, `quality_gate_passed`.
- Внешний Tau-Bench: `pass_rate`, `avg_reward`, `avg_score` если он есть в raw-output.

Для `run_tau_with_1c_agent.py` ключевые поля:

- `Termination Reason`: как закончился диалог (`USER_STOP` и `AGENT_STOP` обычно нормальны, `MAX_STEPS` и infra errors плохи).
- `Reward`: итоговая reward benchmark-задачи.
- `DB Check`: изменилась ли среда так, как ожидает задача.
- `Action Checks`: вызвал ли агент правильные tau-tools с правильными аргументами.
- `NL Assertions`: подтвердил ли агент нужный пользовательский outcome текстом.

Рекомендуемая интерпретация:

- локальный benchmark отвечает на вопрос "решает ли агент наши сценарии в 1С";
- Tau-Bench отвечает на вопрос "как агент/модель выглядит на внешнем tool-use benchmark";
- решение о релизе не должно приниматься только по Tau-Bench.

Практически:

- `Reward=1.0`, `DB Check=1.0`, `Action Checks=✅`, `NL Assertions=✅`:
  задача пройдена полностью.
- `Action Checks=✅`, `DB Check=✅`, но `NL Assertions` отсутствуют:
  запуск был в режиме `evaluation-type=all`, без LLM judge.
- `infra error`:
  проблема в окружении/провайдере/LLM judge, а не обязательно в самом агенте.
- `MAX_STEPS`:
  агент зациклился или не смог завершить задачу в tau-контуре.

## Следующий этап

Если понадобится прогонять в Tau-Bench не просто базовую модель, а именно ваш 1С-агент, нужен bridge-слой:

- адаптер агента с контрактом Tau-Bench;
- маппинг tool-calls Tau-Bench на действия в 1С или отдельную sandbox-среду;
- изоляция write-операций и явная политика безопасности.

Подготовленный scaffold и план внедрения: [docs/TAU_AGENT_BRIDGE.md](../docs/TAU_AGENT_BRIDGE.md)
