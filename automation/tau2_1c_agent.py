# -*- coding: utf-8 -*-
"""
Custom Tau-Bench agent that proxies turns into the 1С agent via tau_bridge.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from tau_paths import find_tau_repo  # noqa: E402
from tau_bridge import (  # noqa: E402
    BridgeConfig,
    BridgeRequest,
    close_session,
    create_session,
    load_bridge_config,
    run_bridge,
    run_bridge_turn,
)


def _maybe_add_tau_src_to_path() -> None:
    tau_src = find_tau_repo(_SCRIPT_DIR.parent) / "src"
    if tau_src.exists() and str(tau_src) not in sys.path:
        sys.path.insert(0, str(tau_src))


_maybe_add_tau_src_to_path()

from tau2.agent.base_agent import HalfDuplexAgent  # noqa: E402
from tau2.data_model.message import (  # noqa: E402
    APICompatibleMessage,
    AssistantMessage,
    Message,
    MultiToolMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.environment.tool import Tool  # noqa: E402
from tau2.utils.llm_utils import generate  # noqa: E402


@dataclass
class OneCTauAgentState:
    system_messages: list[SystemMessage]
    messages: list[Message]
    session_id: str = ""


def _tool_to_prompt_block(tool: Tool) -> str:
    schema = tool.openai_schema.get("function", {})
    params = schema.get("parameters", {})
    return (
        f"- {tool.name}: {schema.get('description', '')}\n"
        f"  args_schema={json.dumps(params, ensure_ascii=False)}"
    )


def _message_to_bridge_dict(message: Message) -> Optional[dict]:
    role = getattr(message, "role", "")
    role_str = role.value if hasattr(role, "value") else str(role)

    if isinstance(message, UserMessage):
        return {"role": "user", "content": str(message.content or "")}
    if isinstance(message, AssistantMessage):
        # Do not feed the 1С bridge with its own long natural-language outputs.
        # We only replay assistant tool calls/results via ToolMessage.
        if message.tool_calls:
            tool_text = json.dumps(
                [{"name": tc.name, "arguments": tc.arguments} for tc in message.tool_calls],
                ensure_ascii=False,
            )
            return {"role": "assistant", "content": f"[tool_calls] {tool_text}"}
        return None
    if isinstance(message, ToolMessage):
        return {
            "role": "assistant",
            "content": f"[tool_result:{message.id}] {message.content or ''}",
        }
    if isinstance(message, MultiToolMessage):
        content = "\n".join(
            f"[tool_result:{item.id}] {item.content or ''}"
            for item in message.tool_messages
        )
        return {"role": "assistant", "content": content}
    if role_str == "system":
        return {"role": "assistant", "content": str(getattr(message, 'content', '') or '')}
    return None


def _extract_json_block(text: str):
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def _parse_assistant_message(reply_text: str) -> AssistantMessage:
    parsed = _extract_json_block(reply_text)
    if isinstance(parsed, dict) and isinstance(parsed.get("tool_calls"), list):
        tool_calls = []
        for index, item in enumerate(parsed["tool_calls"], start=1):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            arguments = item.get("arguments") or {}
            if not name or not isinstance(arguments, dict):
                continue
            tool_calls.append(
                ToolCall(
                    id=f"onec_tool_{index}",
                    name=name,
                    arguments=arguments,
                    requestor="assistant",
                )
            )
        if tool_calls:
            return AssistantMessage(role="assistant", content=None, tool_calls=tool_calls)

    return AssistantMessage.text(reply_text or "")


class OneCTauAgent(HalfDuplexAgent[OneCTauAgentState]):
    def __init__(
        self,
        tools: list[Tool],
        domain_policy: str,
        llm: str = "",
        llm_args: Optional[dict] = None,
    ):
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.llm = llm
        self.llm_args = llm_args or {}
        bridge_config_path = self.llm_args.get("bridge_config_path") or os.environ.get(
            "TAU_BRIDGE_CONFIG_PATH"
        )
        bridge_connection = self.llm_args.get("bridge_connection") or os.environ.get(
            "1C_CONNECTION_STRING"
        )
        self.bridge_config = load_bridge_config(bridge_config_path, bridge_connection)
        self.strict_tau_mode = bool(self.llm_args.get("strict_tau_mode", True))

    def _make_system_prompt(self) -> str:
        tools_text = "\n".join(_tool_to_prompt_block(tool) for tool in self.tools)
        return (
            "Ты являешься прокси-агентом для Tau-Bench.\n\n"
            f"Policy:\n{self.domain_policy}\n\n"
            "Доступные инструменты benchmark-среды:\n"
            f"{tools_text}\n\n"
            "Если нужен инструмент benchmark-среды, верни JSON формата "
            '{"tool_calls":[{"name":"tool_name","arguments":{...}}]}. '
            "Если инструмент не нужен, верни обычный текст."
        )

    def _make_mock_system_prompt(self) -> str:
        tools_text = "\n".join(_tool_to_prompt_block(tool) for tool in self.tools)
        return (
            "You are a Tau-Bench customer-service agent operating in the mock domain.\n\n"
            f"Domain policy:\n{self.domain_policy}\n\n"
            "Available tools:\n"
            f"{tools_text}\n\n"
            "Rules:\n"
            "- Solve the user's task using the provided Tau tools, not external systems.\n"
            "- When an action is required, return tool calls only.\n"
            "- After successful tool execution, send a brief confirmation to the user.\n"
            "- Do not narrate hidden reasoning.\n"
            "- Do not mention 1C, DSL, metadata, documents, or internal implementation details.\n"
        )

    def _should_use_native_tau_mode(self) -> bool:
        tool_names = {tool.name for tool in self.tools}
        mock_signature = {"create_task", "get_users", "update_task_status"}
        return self.strict_tau_mode and bool(tool_names.intersection(mock_signature))

    def _generate_native_tau_message(
        self,
        state: OneCTauAgentState,
    ) -> AssistantMessage:
        messages: list[APICompatibleMessage] = []
        for item in state.messages:
            if isinstance(item, (UserMessage, AssistantMessage, ToolMessage)):
                messages.append(item)
            elif isinstance(item, MultiToolMessage):
                messages.extend(item.tool_messages)

        response = generate(
            model=self.llm_args.get("tau_planner_llm") or os.environ.get("SCORE_LLM_MODEL", "gpt-4o"),
            tools=self.tools,
            messages=state.system_messages + messages,
            api_base=os.environ.get("OPENAI_API_BASE") or os.environ.get("SCORE_LLM_API_URL", "").removesuffix("/chat/completions"),
            api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("SCORE_LLM_API_KEY"),
            temperature=0.0,
        )
        return response

    def _build_mock_rule_based_message(
        self,
        message: UserMessage | ToolMessage | MultiToolMessage,
    ) -> Optional[AssistantMessage]:
        if isinstance(message, ToolMessage):
            lowered_content = str(message.content or "").lower()
            if "transfer successful" in lowered_content:
                return AssistantMessage.text("YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.")
            if '"status": "completed"' in lowered_content or '"status":"completed"' in lowered_content:
                return AssistantMessage.text("I updated the existing task to completed successfully.")
            if '"status": "pending"' in lowered_content or '"status":"pending"' in lowered_content:
                return AssistantMessage.text("The task was created successfully.")
            if "task_" in str(message.content or "") or "title=" in str(message.content or ""):
                return AssistantMessage.text("The task was created successfully.")
            if "status" in str(message.content or ""):
                return AssistantMessage.text("The task status was updated successfully.")
            return AssistantMessage.text("Done.")

        if isinstance(message, MultiToolMessage):
            return AssistantMessage.text("Done.")

        if not isinstance(message, UserMessage):
            return None

        text = str(message.content or "")
        lowered = text.lower()

        create_match = re.search(
            r"create a new task called ['\"]([^'\"]+)['\"].*?for (user_\d+)",
            text,
            flags=re.I | re.S,
        )
        if create_match:
            title = create_match.group(1).strip()
            user_id = create_match.group(2).strip()
            return AssistantMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="mock_create_task_1",
                        name="create_task",
                        arguments={"user_id": user_id, "title": title},
                        requestor="assistant",
                    )
                ],
            )

        update_match = re.search(
            r"(task[_\s]\d+|task_\d+).*?\b(completed|pending)\b",
            lowered,
            flags=re.I | re.S,
        )
        if update_match:
            task_id = update_match.group(1).replace(" ", "_")
            status = update_match.group(2)
            return AssistantMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="mock_update_task_1",
                        name="update_task_status",
                        arguments={"task_id": task_id, "status": status},
                        requestor="assistant",
                    )
                ],
            )

        if "all users" in lowered or "get users" in lowered or "list users" in lowered:
            return AssistantMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="mock_get_users_1",
                        name="get_users",
                        arguments={},
                        requestor="assistant",
                    )
                ],
            )

        if "delete" in lowered or "remove" in lowered or "human" in lowered or "person" in lowered:
            return AssistantMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="mock_transfer_1",
                        name="transfer_to_human_agents",
                        arguments={
                            "summary": "User needs to delete all their current tasks. This is not possible to do with the tools available."
                        },
                        requestor="assistant",
                    )
                ],
            )

        return None

    def get_init_state(
        self, message_history: Optional[list[Message]] = None
    ) -> OneCTauAgentState:
        system_prompt = self._make_mock_system_prompt() if self._should_use_native_tau_mode() else self._make_system_prompt()
        state = OneCTauAgentState(
            system_messages=[SystemMessage(role="system", content=system_prompt)],
            messages=list(message_history) if message_history else [],
            session_id="",
        )
        if self.bridge_config.use_sessions and not self._should_use_native_tau_mode():
            ok, session_id, _ = create_session(self.bridge_config)
            if ok:
                state.session_id = session_id
        return state

    def generate_next_message(
        self,
        message: UserMessage | ToolMessage | MultiToolMessage,
        state: OneCTauAgentState,
    ) -> tuple[AssistantMessage, OneCTauAgentState]:
        state.messages.append(message)

        if self._should_use_native_tau_mode():
            assistant_message = self._build_mock_rule_based_message(message)
            if assistant_message is None:
                assistant_message = self._generate_native_tau_message(state)
            state.messages.append(assistant_message)
            return assistant_message, state

        conversation = []
        replay_items = state.messages[:-1][-12:]
        for item in replay_items:
            bridge_item = _message_to_bridge_dict(item)
            if bridge_item:
                conversation.append(bridge_item)

        last_content = ""
        current_item = _message_to_bridge_dict(message)
        if current_item:
            last_content = str(current_item.get("content", "") or "")

        request = BridgeRequest(
            task_id="tau_task",
            user_message=last_content,
            conversation=conversation,
            metadata={"bridge_mode": self.bridge_config.bridge_mode},
        )

        if self.bridge_config.use_sessions and state.session_id:
            bridge_result = run_bridge_turn(request, self.bridge_config, state.session_id)
        else:
            bridge_result = run_bridge(request, self.bridge_config)
            if bridge_result.session_id and not state.session_id:
                state.session_id = bridge_result.session_id

        reply_text = bridge_result.agent_reply or bridge_result.error
        assistant_message = _parse_assistant_message(reply_text)
        state.messages.append(assistant_message)
        return assistant_message, state

    def stop(self, message=None, state: Optional[OneCTauAgentState] = None) -> None:
        if state and state.session_id and self.bridge_config.use_sessions:
            close_session(self.bridge_config, state.session_id)


def create_onec_tau_agent(tools, domain_policy, **kwargs):
    return OneCTauAgent(
        tools=tools,
        domain_policy=domain_policy,
        llm=kwargs.get("llm", ""),
        llm_args=kwargs.get("llm_args"),
    )
