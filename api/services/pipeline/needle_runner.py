"""Cactus Compute Needle Tool Calling Engine (<25ms).

Provides deterministic function calling, slot extraction, and schema enforcement
bypassing heavy LLMs for transactional workflows (e.g. order lookups, appointment
status, account balance, cancellations).
"""

from __future__ import annotations

import inspect
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("needle")
from pydantic import BaseModel, Field


@dataclass
class NeedleSlot:
    name: str
    pattern: str  # regex pattern to extract value
    slot_type: str = "str"
    required: bool = True
    default: Any = None


@dataclass
class NeedleToolDefinition:
    name: str
    description: str
    intent_patterns: List[str]
    slots: List[NeedleSlot] = field(default_factory=list)
    handler: Optional[Callable[..., Union[Dict[str, Any], str, Awaitable[Union[Dict[str, Any], str]]]]] = None
    response_template: Optional[str] = None
    confidence_threshold: float = 0.75


class NeedleExecutionResult(BaseModel):
    matched: bool = False
    tool_name: Optional[str] = None
    extracted_slots: Dict[str, Any] = Field(default_factory=dict)
    tool_result: Optional[Any] = None
    response_text: Optional[str] = None
    execution_time_ms: float = 0.0
    fallback_to_llm: bool = True


class NeedleRunner:
    """Needle fast-path execution engine with tenant scoping."""

    def __init__(self, tenant_id: Optional[Union[str, int]] = None):
        self.tenant_id = str(tenant_id) if tenant_id is not None else "default"
        self._tools: Dict[str, NeedleToolDefinition] = {}
        self._compiled_intents: Dict[str, List[re.Pattern]] = {}
        self._compiled_slots: Dict[str, Dict[str, re.Pattern]] = {}
        self._native_needle = None
        self._init_native_needle()

    def _init_native_needle(self) -> None:
        try:
            import needle  # type: ignore

            self._native_needle = needle
            logger.info("NeedleRunner: Native 'needle' library loaded successfully.")
        except ImportError:
            logger.info("NeedleRunner: Native 'needle' package not found; using built-in deterministic slot execution engine.")
        except Exception as e:
            logger.warning(f"NeedleRunner: Native needle initialization failed ({e}); using built-in engine.")

    def register_tool(self, tool: NeedleToolDefinition) -> None:
        """Registers a tool schema into the tenant's registry."""
        self._tools[tool.name] = tool
        self._compiled_intents[tool.name] = [
            re.compile(pattern, re.IGNORECASE) for pattern in tool.intent_patterns
        ]
        self._compiled_slots[tool.name] = {
            slot.name: re.compile(slot.pattern, re.IGNORECASE) for slot in tool.slots
        }
        logger.debug(f"NeedleRunner [{self.tenant_id}]: Registered tool '{tool.name}' with {len(tool.slots)} slots.")

    def tool(
        self,
        name: str,
        description: str,
        intent_patterns: List[str],
        slots: Optional[List[NeedleSlot]] = None,
        response_template: Optional[str] = None,
    ):
        """Decorator for registering functions as Needle tools."""
        def decorator(func: Callable):
            tool_def = NeedleToolDefinition(
                name=name,
                description=description,
                intent_patterns=intent_patterns,
                slots=slots or [],
                handler=func,
                response_template=response_template,
            )
            self.register_tool(tool_def)
            return func

        return decorator

    async def execute_transcript(
        self, transcript: str, session_context: Optional[Dict[str, Any]] = None
    ) -> NeedleExecutionResult:
        """Matches transcript against registered tools and executes in <25ms.

        If a match is found and parameters are extracted, executes the tool and formats
        the response buffer. If no match is found, returns matched=False and fallback_to_llm=True.
        """
        start_time = time.perf_counter()
        clean_text = transcript.strip()
        session_context = session_context or {}

        if not clean_text or not self._tools:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return NeedleExecutionResult(matched=False, fallback_to_llm=True, execution_time_ms=elapsed_ms)

        # 1. Match intent
        matched_tool: Optional[NeedleToolDefinition] = None
        for tool_name, compiled_patterns in self._compiled_intents.items():
            for pat in compiled_patterns:
                if pat.search(clean_text):
                    matched_tool = self._tools[tool_name]
                    break
            if matched_tool:
                break

        if not matched_tool:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return NeedleExecutionResult(
                matched=False,
                fallback_to_llm=True,
                execution_time_ms=elapsed_ms,
            )

        # 2. Extract slots
        extracted_slots: Dict[str, Any] = {}
        slot_patterns = self._compiled_slots.get(matched_tool.name, {})

        for slot in matched_tool.slots:
            slot_pat = slot_patterns.get(slot.name)
            if slot_pat:
                match = slot_pat.search(clean_text)
                if match:
                    # Prefer first group if capture groups exist, else full match
                    val = match.group(1) if match.groups() else match.group(0)
                    extracted_slots[slot.name] = self._cast_slot_value(val, slot.slot_type)
                elif slot.name in session_context:
                    extracted_slots[slot.name] = session_context[slot.name]
                elif slot.default is not None:
                    extracted_slots[slot.name] = slot.default
                elif slot.required:
                    # Missing required slot; let System 2 LLM ask or handle
                    logger.debug(f"NeedleRunner: Tool '{matched_tool.name}' matched but missing required slot '{slot.name}'")
                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                    return NeedleExecutionResult(
                        matched=False,
                        tool_name=matched_tool.name,
                        fallback_to_llm=True,
                        execution_time_ms=elapsed_ms,
                    )

        # 3. Execute tool handler
        tool_result: Any = None
        response_text: Optional[str] = None

        if matched_tool.handler:
            try:
                # Inspect handler signature to pass arguments
                sig = inspect.signature(matched_tool.handler)
                kwargs: Dict[str, Any] = {}
                for param_name in sig.parameters.keys():
                    if param_name in extracted_slots:
                        kwargs[param_name] = extracted_slots[param_name]
                    elif param_name == "session_context" or param_name == "context":
                        kwargs[param_name] = session_context

                if inspect.iscoroutinefunction(matched_tool.handler):
                    tool_result = await matched_tool.handler(**kwargs)
                else:
                    tool_result = matched_tool.handler(**kwargs)
            except Exception as e:
                logger.error(f"NeedleRunner: Error executing tool '{matched_tool.name}': {e}")
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return NeedleExecutionResult(
                    matched=True,
                    tool_name=matched_tool.name,
                    extracted_slots=extracted_slots,
                    fallback_to_llm=True,
                    execution_time_ms=elapsed_ms,
                )

        # 4. Generate response buffer from template or return value
        if matched_tool.response_template:
            merge_data = {**session_context, **extracted_slots}
            if isinstance(tool_result, dict):
                merge_data.update(tool_result)
            elif tool_result is not None:
                merge_data["result"] = tool_result

            try:
                response_text = matched_tool.response_template.format(**merge_data)
            except KeyError as ke:
                logger.warning(f"NeedleRunner: Template key error {ke}, returning raw string.")
                response_text = str(tool_result) if tool_result else None
        elif isinstance(tool_result, str):
            response_text = tool_result
        elif tool_result is not None:
            response_text = str(tool_result)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            f"NeedleRunner: Fast-path tool '{matched_tool.name}' executed in {elapsed_ms:.2f}ms"
        )

        return NeedleExecutionResult(
            matched=True,
            tool_name=matched_tool.name,
            extracted_slots=extracted_slots,
            tool_result=tool_result,
            response_text=response_text,
            execution_time_ms=elapsed_ms,
            fallback_to_llm=False if response_text else True,
        )

    @staticmethod
    def _cast_slot_value(val: str, slot_type: str) -> Any:
        try:
            if slot_type == "int":
                return int(val.strip())
            if slot_type == "float":
                return float(val.strip())
            if slot_type == "bool":
                return val.strip().lower() in ("true", "1", "yes")
        except Exception:
            pass
        return val.strip()
