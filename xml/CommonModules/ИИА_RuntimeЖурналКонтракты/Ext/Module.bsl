#Область ПрограммныйИнтерфейс

Функция ПолучитьРеестрDecisionLogPolicy() Экспорт
	Реестр = Новый Соответствие;
	Реестр.Вставить("discovery_rag", Новый Структура("validation_mode,allowed_values", "fixed", Новый Массив));
	Реестр.Получить("discovery_rag").allowed_values.Добавить("rag_on");
	Реестр.Получить("discovery_rag").allowed_values.Добавить("rag_off");
	Реестр.Вставить("execution_policy", Новый Структура("validation_mode,allowed_values", "transition_policy", Новый Массив));
	Реестр.Вставить("next_step_selected", Новый Структура("validation_mode,allowed_values", "freeform", Новый Массив));
	Реестр.Вставить("approval", Новый Структура("validation_mode,allowed_values", "fixed", Новый Массив));
	Реестр.Получить("approval").allowed_values.Добавить("requested");
	Реестр.Получить("approval").allowed_values.Добавить("approved");
	Реестр.Получить("approval").allowed_values.Добавить("rejected");
	Реестр.Вставить("recovery_policy", Новый Структура("validation_mode,allowed_values", "transition_reason", Новый Массив));
	Реестр.Вставить("checkpoint_resume", Новый Структура("validation_mode,allowed_values", "fixed", Новый Массив));
	Реестр.Получить("checkpoint_resume").allowed_values.Добавить("requested");
	Возврат Реестр;
КонецФункции

Функция ПолучитьРеестрEventHistoryPolicy() Экспорт
	Реестр = Новый Массив;
	Реестр.Добавить("stage_transition");
	Возврат Реестр;
КонецФункции

Функция ПолучитьРеестрTransitionEventHistoryPolicy() Экспорт
	Реестр = Новый Массив;
	Реестр.Добавить("cycle_start");
	Реестр.Добавить("resume");
	Реестр.Добавить("intent_done");
	Реестр.Добавить("plan_done");
	Реестр.Добавить("plan_failed");
	Реестр.Добавить("plan_ready");
	Реестр.Добавить("plan_completed");
	Реестр.Добавить("approval_required");
	Реестр.Добавить("approval_approved");
	Реестр.Добавить("approval_rejected");
	Реестр.Добавить("execute_done");
	Реестр.Добавить("execute_failed");
	Реестр.Добавить("validate_default");
	Реестр.Добавить("reset_attempt");
	Реестр.Добавить("recover_handled");
	Реестр.Добавить("recover_failed");
	Реестр.Добавить("recoverable_error");
	Реестр.Добавить("recovery_exhausted");
	Реестр.Добавить("non_recoverable_error");
	Реестр.Добавить("no_executor_result");
	Реестр.Добавить("next_step");
	Реестр.Добавить("unknown_stage");
	Реестр.Добавить("checkpoint_resume");
	Возврат Реестр;
КонецФункции

Функция ПолучитьРеестрCheckpointTracePolicy() Экспорт
	Реестр = Новый Массив;
	Реестр.Добавить("stage_transition");
	Реестр.Добавить("cycle_resumed");
	Реестр.Добавить("cycle_started");
	Реестр.Добавить("discovery_subgraph_evaluated");
	Реестр.Добавить("typed_plan_saved");
	Реестр.Добавить("plan_step_updated");
	Реестр.Добавить("execute_subgraph_selected");
	Реестр.Добавить("execute_subgraph_entered");
	Реестр.Добавить("approval_consumed");
	Реестр.Добавить("approval_requested");
	Реестр.Добавить("approval_approved");
	Реестр.Добавить("approval_rejected");
	Реестр.Добавить("recovery_decision_resume");
	Реестр.Добавить("recovery_decision_abort");
	Реестр.Добавить("recovery_decision_replan");
	Реестр.Добавить("checkpoint_resume_requested");
	Возврат Реестр;
КонецФункции

Функция ПолучитьРеестрSubgraphTracePolicy() Экспорт
	Реестр = Новый Массив;
	Реестр.Добавить("rag_evaluated");
	Реестр.Добавить("enter");
	Реестр.Добавить("plan_completed");
	Реестр.Добавить("next_step_generation");
	Реестр.Добавить("planned_next_step");
	Реестр.Добавить("selected");
	Реестр.Добавить("checkpoint_resume");
	Реестр.Добавить("completed");
	Возврат Реестр;
КонецФункции

Функция НормализоватьKindDecisionLog(DecisionKind) Экспорт
	KindValue = СокрЛП(Строка(DecisionKind));
	Если ПустаяСтрока(KindValue) Тогда
		Возврат "";
	КонецЕсли;
	Реестр = ПолучитьРеестрDecisionLogPolicy();
	Если Реестр.Получить(KindValue) = Неопределено Тогда
		Возврат "";
	КонецЕсли;
	Возврат KindValue;
КонецФункции

Функция НормализоватьТипEventHistory(EventType) Экспорт
	НормЗначение = СокрЛП(Строка(EventType));
	Если ПустаяСтрока(НормЗначение) Тогда
		Возврат "";
	КонецЕсли;
	Если ЭтоЗначениеВСписке(ПолучитьРеестрEventHistoryPolicy(), НормЗначение) Тогда
		Возврат НормЗначение;
	КонецЕсли;
	Возврат "";
КонецФункции

Функция НормализоватьTransitionEventHistory(TransitionValue) Экспорт
	НормЗначение = СокрЛП(Строка(TransitionValue));
	Если ПустаяСтрока(НормЗначение) Тогда
		Возврат "";
	КонецЕсли;
	Если ЭтоЗначениеВСписке(ПолучитьРеестрTransitionEventHistoryPolicy(), НормЗначение) Тогда
		Возврат НормЗначение;
	КонецЕсли;
	Возврат "";
КонецФункции

Функция НормализоватьТипCheckpointTrace(CheckpointType) Экспорт
	НормЗначение = СокрЛП(Строка(CheckpointType));
	Если ПустаяСтрока(НормЗначение) Тогда
		Возврат "";
	КонецЕсли;
	Если ЭтоЗначениеВСписке(ПолучитьРеестрCheckpointTracePolicy(), НормЗначение) Тогда
		Возврат НормЗначение;
	КонецЕсли;
	Возврат "";
КонецФункции

Функция НормализоватьDecisionSubgraphTrace(DecisionValue) Экспорт
	НормЗначение = СокрЛП(Строка(DecisionValue));
	Если ПустаяСтрока(НормЗначение) Тогда
		Возврат "";
	КонецЕсли;
	Если ЭтоЗначениеВСписке(ПолучитьРеестрSubgraphTracePolicy(), НормЗначение) Тогда
		Возврат НормЗначение;
	КонецЕсли;
	Возврат "";
КонецФункции

Функция НормализоватьValueDecisionLog(DecisionKind, DecisionValue) Экспорт
	KindValue = НормализоватьKindDecisionLog(DecisionKind);
	Если ПустаяСтрока(KindValue) Тогда
		Возврат "";
	КонецЕсли;
	ЗначениеРешения = СокрЛП(Строка(DecisionValue));
	Если ПустаяСтрока(ЗначениеРешения) Тогда
		Возврат "";
	КонецЕсли;
	Политика = ПолучитьРеестрDecisionLogPolicy().Получить(KindValue);
	РежимПроверки = ?(Политика <> Неопределено И Политика.Свойство("validation_mode"), Строка(Политика.validation_mode), "");
	Если РежимПроверки = "fixed" Тогда
		Если ЭтоЗначениеВСписке(Политика.allowed_values, ЗначениеРешения) Тогда
			Возврат ЗначениеРешения;
		КонецЕсли;
		Возврат "";
	ИначеЕсли РежимПроверки = "transition_policy" Тогда
		Возврат ИИА_RuntimeКонтракты.НормализоватьTransitionPolicy(ЗначениеРешения);
	ИначеЕсли РежимПроверки = "transition_reason" Тогда
		Возврат ИИА_RuntimeКонтракты.НормализоватьTransitionReason(ЗначениеРешения);
	ИначеЕсли РежимПроверки = "freeform" Тогда
		Возврат ЗначениеРешения;
	КонецЕсли;
	Возврат "";
КонецФункции

#Область СлужебныеПроцедурыИФункции

Функция ЭтоЗначениеВСписке(МассивЗначений, Значение)
	Если ТипЗнч(МассивЗначений) <> Тип("Массив") Тогда
		Возврат Ложь;
	КонецЕсли;
	Для Каждого Элемент Из МассивЗначений Цикл
		Если СокрЛП(Строка(Элемент)) = СокрЛП(Строка(Значение)) Тогда
			Возврат Истина;
		КонецЕсли;
	КонецЦикла;
	Возврат Ложь;
КонецФункции

#КонецОбласти
#КонецОбласти
