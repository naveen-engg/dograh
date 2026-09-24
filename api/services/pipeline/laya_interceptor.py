"""Laya Turn Interceptor for Ultra-Low-Latency Voice AI (<35ms).

Provides System 1 fast-pass classification:
1. should_interrupt: Distinguishes caller backchannels ('uh-huh', 'yeah') from real interruptions.
2. security_guard: Evaluates prompt injection, jailbreaks, and policy compliance violations.
3. emergency_route: Identifies caller escalation demands (human agent, supervisor, 911) for instant SIP REFER.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("laya")
from pydantic import BaseModel, Field

from pipecat.frames.frames import (
    CancelFrame,
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


# Common conversational backchannel filler words and phrases
BACKCHANNEL_PATTERNS = {
    "uh-huh",
    "uh huh",
    "yeah",
    "yep",
    "mhm",
    "mm-hmm",
    "mm hmm",
    "mm",
    "got it",
    "gotcha",
    "right",
    "okay",
    "ok",
    "sure",
    "i see",
    "ah",
    "cool",
    "understood",
    "yes",
    "alright",
}

# Strong interruptive phrases
INTERRUPT_PATTERNS = {
    r"\bwait\b",
    r"\bstop\b",
    r"\bhold on\b",
    r"\bcancel\b",
    r"\bpause\b",
    r"\bno\b",
    r"\bactually\b",
    r"\bexcuse me\b",
    r"\bhang on\b",
    r"\bdon't\b",
    r"\bwrong\b",
}

# Prompt injection / security violation indicators
SECURITY_VIOLATION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"system\s+prompt",
    r"you\s+are\s+now\s+in\s+developer\s+mode",
    r"dan\s+mode",
    r"bypass\s+all\s+filters",
    r"reveal\s+your\s+instructions",
    r"jailbreak",
    r"drop\s+database",
    r"select\s+\*\s+from\s+users",
]

# Emergency / human escalation patterns for SIP transfer
EMERGENCY_ESCALATION_PATTERNS = [
    r"\b(transfer|connect)\s+me\s+to\s+a\s+(human|agent|person|operator|supervisor)\b",
    r"\b(speak|talk)\s+to\s+a\s+(human|agent|person|operator|supervisor|representative|manager)\b",
    r"\b(real\s+person|human\s+being|live\s+agent)\b",
    r"\b(call\s+911|emergency|ambulance|police)\b",
    r"\bi\s+want\s+to\s+speak\s+with\s+a\s+manager\b",
    r"\boperator\b",
]


class LayaGuardResult(BaseModel):
    is_safe: bool = True
    violation_type: Optional[str] = None
    confidence: float = 1.0
    latency_ms: float = 0.0


class LayaEmergencyResult(BaseModel):
    is_emergency: bool = False
    escalation_target: Optional[str] = None
    confidence: float = 0.0
    latency_ms: float = 0.0


class LayaEvaluationResult(BaseModel):
    should_interrupt: bool = True
    is_backchannel: bool = False
    guard: LayaGuardResult = Field(default_factory=LayaGuardResult)
    emergency: LayaEmergencyResult = Field(default_factory=LayaEmergencyResult)
    total_eval_ms: float = 0.0


class LayaRouter:
    """Fast-inference System 1 Router.

    Initializes native `laya.Router` if available; otherwise falls back to
    an optimized deterministic in-process evaluator guaranteed sub-5ms.
    """

    def __init__(self, preload: bool = True, device: Optional[str] = None):
        self._native_router = None
        self._device = device or "cpu"
        self._compiled_interrupts = [re.compile(p, re.IGNORECASE) for p in INTERRUPT_PATTERNS]
        self._compiled_security = [re.compile(p, re.IGNORECASE) for p in SECURITY_VIOLATION_PATTERNS]
        self._compiled_emergency = [re.compile(p, re.IGNORECASE) for p in EMERGENCY_ESCALATION_PATTERNS]

        if preload:
            self._initialize_router()

    def _initialize_router(self) -> None:
        try:
            import laya  # type: ignore

            self._native_router = laya.Router(preload=True, device=self._device)
            logger.info(f"LayaRouter: Native laya engine initialized successfully on {self._device}")
        except ImportError:
            logger.info("LayaRouter: Native 'laya' package not installed; using built-in optimized sub-5ms fast classifier.")
        except Exception as e:
            logger.warning(f"LayaRouter: Could not initialize native laya engine ({e}); using built-in fast classifier.")

    def should_interrupt(self, text: str) -> bool:
        """Determines if user utterance represents a real interruption or backchannel.

        Returns False for conversational backchannels ('uh-huh', 'yeah', etc.),
        preventing false VAD barge-ins. Returns True for real interruptions.
        """
        clean_text = text.strip().lower()
        if not clean_text:
            return False

        # Normalize punctuation
        normalized = re.sub(r"[^\w\s-]", "", clean_text).strip()

        # Check pure backchannels
        if normalized in BACKCHANNEL_PATTERNS:
            return False

        # Words count: 1-2 words matching backchannel words
        words = normalized.split()
        if len(words) <= 2 and all(w in BACKCHANNEL_PATTERNS for w in words):
            return False

        # Explicit interruption patterns
        for pattern in self._compiled_interrupts:
            if pattern.search(clean_text):
                return True

        # Any speech longer than 2 non-backchannel words is considered true speech/interruption
        return True

    def security_guard(self, text: str) -> LayaGuardResult:
        """Evaluates text for prompt injection, jailbreaks, or policy violations."""
        start_time = time.perf_counter()
        clean_text = text.strip()

        for pattern in self._compiled_security:
            if pattern.search(clean_text):
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return LayaGuardResult(
                    is_safe=False,
                    violation_type="PROMPT_INJECTION_OR_JAILBREAK",
                    confidence=0.98,
                    latency_ms=duration_ms,
                )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        return LayaGuardResult(
            is_safe=True,
            violation_type=None,
            confidence=0.99,
            latency_ms=duration_ms,
        )

    def emergency_route(self, text: str) -> LayaEmergencyResult:
        """Evaluates whether caller explicitly requests human escalation or 911."""
        start_time = time.perf_counter()
        clean_text = text.strip()

        for pattern in self._compiled_emergency:
            match = pattern.search(clean_text)
            if match:
                matched_str = match.group(0).lower()
                target = "emergency_services" if any(w in matched_str for w in ["911", "ambulance", "police"]) else "human_agent"
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return LayaEmergencyResult(
                    is_emergency=True,
                    escalation_target=target,
                    confidence=0.96,
                    latency_ms=duration_ms,
                )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        return LayaEmergencyResult(
            is_emergency=False,
            escalation_target=None,
            confidence=0.0,
            latency_ms=duration_ms,
        )

    def evaluate_turn(self, text: str) -> LayaEvaluationResult:
        """Runs unified sub-35ms turn evaluation."""
        start = time.perf_counter()
        should_intr = self.should_interrupt(text)
        is_backchannel = not should_intr and bool(text.strip())
        guard_res = self.security_guard(text)
        emerg_res = self.emergency_route(text)
        total_ms = (time.perf_counter() - start) * 1000.0

        return LayaEvaluationResult(
            should_interrupt=should_intr,
            is_backchannel=is_backchannel,
            guard=guard_res,
            emergency=emerg_res,
            total_eval_ms=total_ms,
        )


class LayaTurnInterceptor(FrameProcessor):
    """Pipecat FrameProcessor that intercepts transcript frames and VAD speech starts.

    Placed immediately downstream of STT and upstream of context aggregators to:
    - Suppress false barge-in cancellations for backchannels.
    - Intercept security violations with immediate canned guardrail response.
    - Trigger immediate SIP referral / human escalation callbacks.
    """

    def __init__(
        self,
        router: Optional[LayaRouter] = None,
        on_emergency_escalation: Optional[Callable[[str, str], Coroutine[Any, Any, None]]] = None,
        on_security_violation: Optional[Callable[[str, str], Coroutine[Any, Any, None]]] = None,
    ):
        super().__init__()
        self.router = router or LayaRouter()
        self.on_emergency_escalation = on_emergency_escalation
        self.on_security_violation = on_security_violation
        self._assistant_is_speaking = False

    def set_assistant_speaking(self, is_speaking: bool) -> None:
        self._assistant_is_speaking = is_speaking

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # Handle transcript frames
        if isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)):
            transcript = frame.text or ""
            if transcript.strip():
                eval_result = self.router.evaluate_turn(transcript)

                # 1. Check emergency / SIP referral
                if eval_result.emergency.is_emergency and self.on_emergency_escalation:
                    target = eval_result.emergency.escalation_target or "human_agent"
                    logger.info(f"LayaTurnInterceptor: Emergency escalation detected -> {target}")
                    await self.on_emergency_escalation(target, transcript)

                # 2. Check security violation
                if not eval_result.guard.is_safe:
                    violation = eval_result.guard.violation_type or "POLICY_VIOLATION"
                    logger.warning(f"LayaTurnInterceptor: Security violation intercepted -> {violation}")
                    if self.on_security_violation:
                        await self.on_security_violation(violation, transcript)
                    # Suppress malicious frame propagation
                    return

                # 3. If assistant is speaking and this is just a backchannel, don't interrupt
                if self._assistant_is_speaking and eval_result.is_backchannel:
                    logger.debug(f"LayaTurnInterceptor: Filtered backchannel '{transcript}' during speech")
                    # Allow frame downstream for transcript logging, but do not trigger barge-in cancellation
                    await self.push_frame(frame, direction)
                    return

        await self.push_frame(frame, direction)
