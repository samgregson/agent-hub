from collections.abc import Sequence
from typing import Any, cast

from ag_ui.core import Interrupt as AGUIInterrupt
from ag_ui.core import ResumeEntry, ToolCallStartEvent
from ag_ui_langgraph import LangGraphAgent
from ag_ui_langgraph.interrupts import lg_interrupts_to_agui
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.types import Command

_HITL_METADATA_KEY = "agentHubLangChainHITL"


def _pending_tool_calls(messages: Sequence[BaseMessage]) -> list[Any]:
    answered = {message.tool_call_id for message in messages if isinstance(message, ToolMessage)}
    return [
        tool_call
        for message in messages
        if isinstance(message, AIMessage)
        for tool_call in message.tool_calls
        if tool_call.get("id") not in answered
    ]


def _hitl_interrupts(
    raw_interrupt: object, tool_calls: Sequence[dict[str, Any]]
) -> list[AGUIInterrupt] | None:
    raw = getattr(raw_interrupt, "value", None)
    if not isinstance(raw, dict):
        return None
    actions = raw.get("action_requests")
    configs = raw.get("review_configs")
    raw_id = getattr(raw_interrupt, "id", None)
    if not raw_id or not isinstance(actions, list) or not isinstance(configs, list):
        return None
    if not actions or len(actions) != len(configs):
        return None

    available = list(tool_calls)
    mapped: list[AGUIInterrupt] = []
    for index, (action, config) in enumerate(zip(actions, configs, strict=True)):
        if not isinstance(action, dict) or not isinstance(config, dict):
            return None
        allowed_decisions = config.get("allowed_decisions")
        if not isinstance(allowed_decisions, list) or not {
            "approve",
            "reject",
        }.issubset(allowed_decisions):
            return None
        action_name = action.get("name")
        action_args = action.get("args")
        match_index = next(
            (
                candidate_index
                for candidate_index, candidate in enumerate(available)
                if candidate.get("name") == action_name and candidate.get("args") == action_args
            ),
            None,
        )
        if match_index is None:
            return None
        tool_call = available.pop(match_index)
        interrupt_id = raw_id if len(actions) == 1 else f"{raw_id}:{index}"
        mapped.append(
            AGUIInterrupt(
                id=interrupt_id,
                reason="tool_call",
                message=(
                    action.get("description")
                    if isinstance(action.get("description"), str)
                    else None
                ),
                tool_call_id=str(tool_call["id"]),
                metadata={
                    _HITL_METADATA_KEY: {
                        "rawInterruptId": raw_id,
                        "actionIndex": index,
                        "allowedDecisions": allowed_decisions,
                    }
                },
            )
        )
    return mapped


def map_langchain_interrupts(
    raw_interrupts: Sequence[object], messages: Sequence[BaseMessage]
) -> list[AGUIInterrupt]:
    tool_calls = _pending_tool_calls(messages)
    mapped: list[AGUIInterrupt] = []
    for raw_interrupt in raw_interrupts:
        hitl = _hitl_interrupts(raw_interrupt, tool_calls)
        mapped.extend(hitl or lg_interrupts_to_agui([raw_interrupt]))
    return mapped


class AgentHubLangGraphAgent(LangGraphAgent):  # type: ignore[misc]
    """Adapts LangChain HITL batches to portable AG-UI tool approvals."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._visible_tool_calls: list[dict[str, Any]] = []

    def _dispatch_event(self, event: Any) -> Any:
        dispatched = super()._dispatch_event(event)
        if isinstance(dispatched, ToolCallStartEvent):
            self._visible_tool_calls.append(
                {
                    "id": dispatched.tool_call_id,
                    "name": dispatched.tool_call_name,
                    "args": None,
                }
            )
        return dispatched

    def _interrupts_to_agui(self, raw_interrupts: Sequence[object]) -> list[AGUIInterrupt]:
        # Streamed calls do not expose their parsed arguments here. LangChain's
        # HITL action request does, so match by stable order and name for the
        # live stream. Reload uses `map_langchain_interrupts`, which can match
        # the complete checkpoint messages by both name and arguments.
        calls = list(self._visible_tool_calls)
        for raw_interrupt in raw_interrupts:
            raw = getattr(raw_interrupt, "value", None)
            actions = raw.get("action_requests") if isinstance(raw, dict) else None
            if isinstance(actions, list):
                available = list(calls)
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    match_index = next(
                        (
                            index
                            for index, call in enumerate(available)
                            if call.get("name") == action.get("name")
                        ),
                        None,
                    )
                    if match_index is not None:
                        available.pop(match_index)["args"] = action.get("args")
        mapped: list[AGUIInterrupt] = []
        for raw_interrupt in raw_interrupts:
            hitl = _hitl_interrupts(raw_interrupt, calls)
            mapped.extend(hitl or lg_interrupts_to_agui([raw_interrupt]))
        return mapped

    def _build_command_from_agui_resume(
        self,
        entries: list[ResumeEntry],
        *,
        open_interrupts: list[AGUIInterrupt] | None = None,
    ) -> Command[Any]:
        if not open_interrupts or not all(
            isinstance(interrupt.metadata, dict) and _HITL_METADATA_KEY in interrupt.metadata
            for interrupt in open_interrupts
        ):
            return cast(
                Command[Any],
                super()._build_command_from_agui_resume(entries, open_interrupts=open_interrupts),
            )

        entries_by_id = {entry.interrupt_id: entry for entry in entries}
        decisions_by_raw: dict[str, list[tuple[int, dict[str, str]]]] = {}
        for interrupt in open_interrupts:
            metadata = interrupt.metadata or {}
            binding = metadata[_HITL_METADATA_KEY]
            if not isinstance(binding, dict):
                raise ValueError("Malformed Agent Hub HITL interrupt metadata")
            entry = entries_by_id.get(interrupt.id)
            if entry is None:
                raise ValueError(f"Missing response for interrupt {interrupt.id}")
            payload = entry.payload if isinstance(entry.payload, dict) else {}
            approved = payload.get("approved") if entry.status == "resolved" else False
            if approved is True:
                decision = {"type": "approve"}
            elif approved is False:
                reason = payload.get("reason")
                decision = {"type": "reject"}
                if isinstance(reason, str) and reason:
                    decision["message"] = reason
            else:
                raise ValueError(f"Interrupt {interrupt.id} requires an approval decision")
            raw_id = binding.get("rawInterruptId")
            action_index = binding.get("actionIndex")
            if not isinstance(raw_id, str) or not isinstance(action_index, int):
                raise ValueError("Malformed Agent Hub HITL interrupt binding")
            decisions_by_raw.setdefault(raw_id, []).append((action_index, decision))

        payloads = {
            raw_id: {
                "decisions": [decision for _, decision in sorted(indexed, key=lambda item: item[0])]
            }
            for raw_id, indexed in decisions_by_raw.items()
        }
        if len(payloads) == 1:
            return Command(resume=next(iter(payloads.values())))
        return Command(resume=payloads)
