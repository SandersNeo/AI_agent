# -*- coding: utf-8 -*-
"""
Deterministic low-cost Tau-Bench user for the mock domain.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from tau2.data_model.message import (
    AssistantMessage,
    Message,
    MultiToolMessage,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from tau2.user.user_simulator_base import HalfDuplexUser, UserState


class CheapMockUserState(UserState):
    initial_sent: bool = False
    compliment_requested: bool = False
    awaiting_compliment: bool = False


def _extract_task_id(text: str) -> str:
    match = re.search(r"\b(task_\d+)\b", text or "", re.IGNORECASE)
    return match.group(1) if match else "task_1"


def _extract_create_request(text: str) -> Optional[str]:
    match = re.search(
        r"task called ['\"]([^'\"]+)['\"].*?\bfor\s+(user_\d+)\b",
        text or "",
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        title, user_id = match.groups()
        return f"Please create a new task called '{title}' for {user_id}."
    return None


def _build_initial_request(instructions: str, history: list[Message]) -> str:
    text = instructions or ""

    create_request = _extract_create_request(text)
    if create_request:
        return create_request

    if "delete all your current tasks" in text.lower():
        return "I want to delete all my current tasks."

    if "mark" in text.lower() and "completed" in text.lower():
        task_id = _extract_task_id(text)
        if task_id == "task_1":
            for message in reversed(history):
                content = getattr(message, "content", "") or ""
                task_id = _extract_task_id(content)
                if task_id != "task_1" or "task_1" in content:
                    break
        return f"Please mark {task_id} as completed."

    cleaned = re.sub(r"^\s*You are [^.]+\.\s*", "", text.strip(), flags=re.IGNORECASE)
    return cleaned or "Please help with my task."


def _message_text(message: Message) -> str:
    if isinstance(message, MultiToolMessage):
        return "\n".join((tool_message.content or "") for tool_message in message.tool_messages)
    return str(getattr(message, "content", "") or "")


def _needs_compliment(instructions: str) -> bool:
    lowered = (instructions or "").lower()
    return "request a compliment" in lowered or "compliment" in lowered


def _looks_like_task_done(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "created successfully",
        "updated successfully",
        "updated the existing task",
        "marked as completed",
        "status was updated",
        "task was created",
        "task has been created",
        "task status",
        "transferred to a human agent",
        "please hold on",
        "you are being transferred",
    )
    return any(marker in lowered for marker in markers)


class CheapMockUser(HalfDuplexUser[CheapMockUserState]):
    def __init__(
        self,
        llm: str | None = None,
        instructions: Optional[str] = None,
        tools=None,
        llm_args: Optional[dict] = None,
    ):
        super().__init__(instructions=instructions, tools=tools)
        self.llm = llm or "deterministic"
        self.llm_args = llm_args or {}

    def set_seed(self, seed: int) -> None:
        return None

    def get_init_state(
        self, message_history: Optional[list[Message]] = None
    ) -> CheapMockUserState:
        return CheapMockUserState(
            system_messages=[],
            messages=list(message_history or []),
        )

    def generate_next_message(
        self, message: AssistantMessage | ToolMessage | MultiToolMessage, state: CheapMockUserState
    ) -> tuple[UserMessage, CheapMockUserState]:
        if isinstance(message, MultiToolMessage):
            state.messages.extend(message.tool_messages)
        else:
            state.messages.append(message)

        if not state.initial_sent:
            state.initial_sent = True
            response_text = _build_initial_request(self.instructions or "", state.messages)
        else:
            incoming_text = _message_text(message)
            if state.awaiting_compliment:
                response_text = "###STOP###"
            elif _needs_compliment(self.instructions or "") and not state.compliment_requested and _looks_like_task_done(incoming_text):
                state.compliment_requested = True
                state.awaiting_compliment = True
                response_text = "Also, could you compliment me?"
            elif _looks_like_task_done(incoming_text):
                response_text = "###STOP###"
            else:
                response_text = _build_initial_request(self.instructions or "", state.messages)

        user_message = UserMessage(role="user", content=response_text)
        state.messages.append(user_message)
        return user_message, state
