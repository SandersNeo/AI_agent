# Итог LangGraph-Adaptation

## Зачем

В проекте реализован не LangGraph как зависимость, а LangGraph-style runtime:

- durable execution через checkpoints;
- explicit state machine и subgraphs;
- approval / interrupt / resume;
- replay safety и idempotency discipline;
- policy registry и runtime journal;
- investigation API и runtime metrics.

Это уже не roadmap, а фактическое описание текущего состояния оркестратора.

## Целевая модель

```mermaid
graph TD
    Intent[Intent] --> Plan[PlanningSubgraph]
    Plan --> Execute[ExecuteSubgraph]
    Execute --> Validate[ValidateSubgraph]
    Validate --> Plan
    Validate --> Recover[RecoverySubgraph]
    Validate --> Summarize[SummarizeSubgraph]
    Recover --> Execute
    Recover --> Plan
    Recover --> Summarize
    Execute --> AwaitApproval[AwaitApproval]
    AwaitApproval --> Execute
    Summarize --> Stop((Stop))
```

## Подграфы

- `DiscoverySubgraph`: RAG/discovery и первичный выбор `execution_policy`
- `PlanningSubgraph`: генерация следующего DSL-шага и `active_step_id`
- `WriteActionSubgraph`: write-path, approval gate, operation discipline
- `ReadQuerySubgraph`: read/query-path
- `GenericExecuteSubgraph`: прочие безопасные execution-ветки
- `ValidateSubgraph`: post-execution validation и переход `Plan / Recover / Summarize`
- `RecoverySubgraph`: `resume / replan / abort`
- `SummarizeSubgraph`: финальная проверка и summary

### PlanningSubgraph

```mermaid
graph TD
    P0[Enter PlanningSubgraph] --> P1{Typed plan exists?}
    P1 -->|no| P2[Initialize plan]
    P1 -->|yes| P3{Plan completed?}
    P2 --> P3
    P3 -->|yes| P4[Decision: continue]
    P4 --> P5[NextStage: Summarize]
    P3 -->|no| P6[Select next pending step]
    P6 --> P7[Set execution_policy and active_step_id]
    P7 --> P8[Generate next DSL]
    P8 --> P9{DSL produced?}
    P9 -->|no| P10[Decision: recover]
    P10 --> P11[NextStage: Recover]
    P9 -->|yes| P12[Save planner artifact and checkpoint]
    P12 --> P13[Decision: continue]
    P13 --> P14[NextStage: Execute]
```

### WriteActionSubgraph

```mermaid
graph TD
    W0[Enter WriteActionSubgraph] --> W1[Checkpoint: execute_subgraph_entered]
    W1 --> W2[Attach operation_id if missing]
    W2 --> W3[Risk evaluation]
    W3 --> W4{Approval required?}
    W4 -->|yes| W5[Save approval state]
    W5 --> W6[Decision: await_approval]
    W6 --> W7[NextStage: AwaitApproval]
    W4 -->|no| W8[Execute DSL]
    W8 --> W9[Append side_effect_log with replay_safety]
    W9 --> W10{Executor success?}
    W10 -->|yes| W11[Decision: continue]
    W11 --> W12[NextStage: Validate]
    W10 -->|no| W13[Decision: recover]
    W13 --> W14[NextStage: Recover]
```

### ValidateSubgraph

```mermaid
graph TD
    V0[Enter ValidateSubgraph] --> V1{Executor result exists?}
    V1 -->|no| V2[Decision: recover]
    V2 --> V3[NextStage: Recover]
    V1 -->|yes| V4{Executor success?}
    V4 -->|yes| V5[Mark plan step done]
    V5 --> V6{Plan completed?}
    V6 -->|yes| V7[Decision: continue]
    V7 --> V8[NextStage: Summarize]
    V6 -->|no| V9[Decision: continue]
    V9 --> V10[NextStage: Plan]
    V4 -->|no| V11{Recoverable error?}
    V11 -->|yes| V12{Attempts exhausted?}
    V12 -->|yes| V13[Decision: recover]
    V13 --> V14[NextStage: Summarize]
    V12 -->|no| V15[Decision: recover]
    V15 --> V16[NextStage: Recover]
    V11 -->|no| V17[Decision: recover]
    V17 --> V18[NextStage: Recover]
```

### RecoverySubgraph

```mermaid
graph TD
    R0[Enter RecoverySubgraph] --> R1[Read executor error]
    R1 --> R2[Select recovery policy]
    R2 --> R3{Policy outcome}
    R3 -->|resume| R4[Decision: resume]
    R4 --> R5[Checkpoint + decision_log]
    R5 --> R6[NextStage: Execute or Validate]
    R3 -->|replan| R7[Decision: replan]
    R7 --> R8[Checkpoint + decision_log]
    R8 --> R9[NextStage: Plan]
    R3 -->|abort| R10[Decision: abort]
    R10 --> R11[Checkpoint + decision_log]
    R11 --> R12[NextStage: Summarize]
```

### SummarizeSubgraph

```mermaid
graph TD
    S0[Enter SummarizeSubgraph] --> S1[Final verification]
    S1 --> S2[Generate summary]
    S2 --> S3[Write final dialog message]
    S3 --> S4[Decision: continue]
    S4 --> S5[Terminal stop]
```

## Runtime State Contract

Минимальный runtime state уже формализован:

- `thread_id`
- `trace_id`
- `current_stage`
- `last_transition`
- `attempt_no`
- `execution_policy`
- `active_subgraph`
- `subgraph_history`
- `decision_log`
- `active_step_id`
- `approval_state`
- `side_effect_log`
- `checkpoint_history`

## Transition Contract

Каждый subgraph возвращает единый `SubgraphResult`:

- `Decision`
- `NextStage`
- `Reason`
- `Policy`
- `StepId`
- `Transition`
- `ExecutorResult`
- `ApprovalPending`

Все `decision / reason / policy` нормализуются через centralized registry. Ad hoc значения в runtime contract больше не считаются допустимыми.

## Durable Execution

```mermaid
graph LR
    A[State Transition] --> B[Event History]
    A --> C[Checkpoint History]
    B --> D[Runtime Trace API]
    C --> D
    D --> E[Investigation / Metrics / Replay]
```

В рантайме есть:

- `checkpoint history`
- `checkpoint diff`
- `runtime trace`
- `resume from checkpoint`
- `decision timeline`

## Approval / Interrupt / Resume

```mermaid
graph TD
    Write[WriteActionSubgraph] --> Risk{Risk Gate}
    Risk -->|safe| Execute[Execute]
    Risk -->|approval_required| Await[AwaitApproval]
    Await -->|approved| Resume[Resume From Checkpoint]
    Await -->|rejected| Replan[Plan]
    Resume --> Execute
```

Approval semantics формализованы:

- `requested`
- `approved`
- `rejected`

И на каждое решение пишутся:

- `decision_log`
- checkpoint
- state update

## Replay Safety / Idempotency

Есть три replay-класса:

- `safe_replay`
- `resume_only`
- `no_replay`

Источники truth для replay policy:

1. `checkpoint details.replay_safety`
2. `side_effect_log.replay_safety`
3. fallback-анализ `PlannedDSL`

Для write-path действует `operation_id` discipline. `resume from checkpoint` блокируется для `no_replay`.

## Policy Layer

Policy registry покрывает:

- `decision_log kind/value`
- `checkpoint_type`
- `subgraph_history decision`
- `event_history event_type`
- state transition values
- `decision / reason / policy` в `SubgraphResult`

Это значит, что весь runtime journal проходит через один policy layer, а не через разрозненные строки по коду.

## Observability

### Runtime Trace

Нормализованный trace event содержит:

- `timestamp`
- `trace_type`
- `kind`
- `decision`
- `source`
- `step_id`
- `policy`
- `reason`
- `subgraph`
- `stage`
- `transition`
- `attempt`
- `trace_id`
- `thread_id`
- `details`

### Metrics

Серверный metrics API возвращает:

- `approval_requested / approved / rejected / approval_rate`
- `recovery_resume_count / replan_count / abort_count / recovery_success_rate`
- `checkpoint_count`
- `decision_count`
- `top_failure_reasons`
- `execution_path_frequency`
- `transition_frequency`
- `retry_count_per_policy`
- `stage_outcome_metrics`

## Investigation API

Для расследования сбоев добавлены:

- `ПолучитьЦепочкиСбоевОркестратора()`
- `ПочемуОстановилсяОркестратор()`

Они используют unified runtime trace и checkpoint history, а не частные логи.

## Текущее отличие от исходного плана

Исходный `LANGGRAPH_ADOPTION_PLAN.md` больше не нужен как backlog: его ключевые пункты реализованы и перенесены сюда в виде итоговой архитектуры.

## Практический итог

Оркестратор теперь ближе не к "циклу с if-ветками", а к graph-runtime:

- стадии оформлены как subgraphs с единым контрактом;
- side effects отделены от replay semantics;
- recovery и approval формализованы;
- runtime state пригоден для replay, дебага и метрик;
- investigation не зависит от ручного чтения логов.

Это и есть полезная часть LangGraph-подхода, перенесенная в текущую 1С-архитектуру без переписывания оркестратора с нуля.
