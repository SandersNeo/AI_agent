#Область ПрограммныйИнтерфейс

Функция СоздатьРезультатПодграфа(SubgraphName, Успех = Ложь, Transition = "", ExecutorResult = Неопределено, ApprovalPending = Ложь, Decision = "", Details = Неопределено, NextStage = "", Reason = "", Policy = "", StepId = "") Экспорт
	Результат = Новый Структура;
	Результат.Вставить("SubgraphName", SubgraphName);
	Результат.Вставить("Успех", Успех);
	Результат.Вставить("Transition", Transition);
	Результат.Вставить("ExecutorResult", ExecutorResult);
	Результат.Вставить("ApprovalPending", ApprovalPending);
	Результат.Вставить("Decision", НормализоватьTransitionDecision(Decision));
	Результат.Вставить("Details", ?(Details = Неопределено, Новый Структура, Details));
	Результат.Вставить("NextStage", NextStage);
	Результат.Вставить("Reason", НормализоватьTransitionReason(Reason));
	Результат.Вставить("Policy", НормализоватьTransitionPolicy(Policy));
	Результат.Вставить("StepId", StepId);
	Возврат Результат;
КонецФункции

Функция ПолучитьРеестрTransitionContract() Экспорт
	Реестр = Новый Структура;
	Реестр.Вставить("Decisions", Новый Массив);
	Реестр.Decisions.Добавить("continue");
	Реестр.Decisions.Добавить("recover");
	Реестр.Decisions.Добавить("await_approval");
	Реестр.Decisions.Добавить("resume");
	Реестр.Decisions.Добавить("replan");
	Реестр.Decisions.Добавить("abort");
	
	Реестр.Вставить("Reasons", Новый Массив);
	Реестр.Reasons.Добавить("discovery_completed");
	Реестр.Reasons.Добавить("plan_failed");
	Реестр.Reasons.Добавить("init_plan_failed");
	Реестр.Reasons.Добавить("plan_completed");
	Реестр.Reasons.Добавить("no_pending_step");
	Реестр.Reasons.Добавить("planner_empty_dsl");
	Реестр.Reasons.Добавить("plan_ready");
	Реестр.Reasons.Добавить("execute_failed");
	Реестр.Reasons.Добавить("approval_required");
	Реестр.Reasons.Добавить("execute_completed");
	Реестр.Reasons.Добавить("recover_handled");
	Реестр.Reasons.Добавить("recover_failed");
	Реестр.Reasons.Добавить("resume_after_committed_write");
	Реестр.Reasons.Добавить("abort_unsafe_write_retry");
	Реестр.Reasons.Добавить("abort_missing_same_operation");
	Реестр.Reasons.Добавить("resume_same_operation_id");
	Реестр.Reasons.Добавить("approval_approved");
	Реестр.Reasons.Добавить("approval_rejected");
	Реестр.Reasons.Добавить("reset_attempt");
	Реестр.Reasons.Добавить("recover_resume");
	Реестр.Reasons.Добавить("recover_abort");
	Реестр.Reasons.Добавить("capability_abort");
	Реестр.Reasons.Добавить("validate_ok");
	Реестр.Reasons.Добавить("no_executor_result");
	Реестр.Reasons.Добавить("next_step");
	Реестр.Reasons.Добавить("recoverable_error");
	Реестр.Reasons.Добавить("recovery_exhausted");
	Реестр.Reasons.Добавить("non_recoverable_error");
	Реестр.Reasons.Добавить("summary_completed");
	Реестр.Reasons.Добавить("summary_failed");
	Реестр.Reasons.Добавить("stage_policy_safe_replay");
	Реестр.Reasons.Добавить("stage_policy_resume_only");
	Реестр.Reasons.Добавить("stage_policy_no_replay");
	
	Реестр.Вставить("Policies", Новый Массив);
	Реестр.Policies.Добавить("safe-path");
	Реестр.Policies.Добавить("fast-path");
	Реестр.Policies.Добавить("planner_policy");
	Для Каждого Пара Из ИИА_RecoveryPolicy.ПолучитьРеестрПолитикВосстановления() Цикл
		Если Пара.Значение <> Неопределено
			И ТипЗнч(Пара.Значение) = Тип("Структура")
			И Пара.Значение.Свойство("id")
			И НЕ ПустаяСтрока(СокрЛП(Строка(Пара.Значение.id)))
			И НЕ ЭтоЗначениеУжеВСписке(Реестр.Policies, Строка(Пара.Значение.id)) Тогда
			Реестр.Policies.Добавить(Строка(Пара.Значение.id));
		КонецЕсли;
	КонецЦикла;
	Реестр.Policies.Добавить("write_retry_committed_policy");
	Реестр.Policies.Добавить("write_retry_missing_operation_id_policy");
	Реестр.Policies.Добавить("write_retry_missing_planned_dsl_policy");
	Реестр.Policies.Добавить("validate_policy");
	Реестр.Policies.Добавить("summarize_policy");
	Реестр.Policies.Добавить("stage_execute_resume_only");
	Реестр.Policies.Добавить("stage_validate_safe_replay");
	Реестр.Policies.Добавить("stage_recover_resume_only");
	Реестр.Policies.Добавить("stage_summarize_safe_replay");
	
	Возврат Реестр;
КонецФункции

Функция ЭтоЗначениеУжеВСписке(СписокЗначений, Значение)
	Для Каждого ТекущееЗначение Из СписокЗначений Цикл
		Если СокрЛП(Строка(ТекущееЗначение)) = СокрЛП(Строка(Значение)) Тогда
			Возврат Истина;
		КонецЕсли;
	КонецЦикла;
	Возврат Ложь;
КонецФункции

Функция НормализоватьЗначениеTransitionRegistry(Категория, Значение)
	НормализованноеЗначение = СокрЛП(Строка(Значение));
	Если ПустаяСтрока(НормализованноеЗначение) Тогда
		Возврат "";
	КонецЕсли;
	Реестр = ПолучитьРеестрTransitionContract();
	ДопустимыеЗначения = Новый Массив;
	Если Категория = "decision" Тогда
		ДопустимыеЗначения = Реестр.Decisions;
	ИначеЕсли Категория = "reason" Тогда
		ДопустимыеЗначения = Реестр.Reasons;
	ИначеЕсли Категория = "policy" Тогда
		ДопустимыеЗначения = Реестр.Policies;
	КонецЕсли;
	Если ЭтоЗначениеУжеВСписке(ДопустимыеЗначения, НормализованноеЗначение) Тогда
		Возврат НормализованноеЗначение;
	КонецЕсли;
	Возврат "";
КонецФункции

Функция НормализоватьTransitionDecision(Decision) Экспорт
	Возврат НормализоватьЗначениеTransitionRegistry("decision", Decision);
КонецФункции

Функция НормализоватьTransitionReason(Reason) Экспорт
	Возврат НормализоватьЗначениеTransitionRegistry("reason", Reason);
КонецФункции

Функция НормализоватьTransitionPolicy(Policy) Экспорт
	Возврат НормализоватьЗначениеTransitionRegistry("policy", Policy);
КонецФункции

Функция ПодготовитьРезультатПодграфаКВозврату(РезультатПодграфа) Экспорт
	Если РезультатПодграфа = Неопределено Или ТипЗнч(РезультатПодграфа) <> Тип("Структура") Тогда
		Возврат РезультатПодграфа;
	КонецЕсли;
	Если РезультатПодграфа.Свойство("Decision") Тогда
		РезультатПодграфа.Decision = НормализоватьTransitionDecision(РезультатПодграфа.Decision);
	КонецЕсли;
	Если РезультатПодграфа.Свойство("Reason") Тогда
		РезультатПодграфа.Reason = НормализоватьTransitionReason(РезультатПодграфа.Reason);
	КонецЕсли;
	Если РезультатПодграфа.Свойство("Policy") Тогда
		РезультатПодграфа.Policy = НормализоватьTransitionPolicy(РезультатПодграфа.Policy);
	КонецЕсли;
	Возврат РезультатПодграфа;
КонецФункции


#КонецОбласти

