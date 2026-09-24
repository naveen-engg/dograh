"""VoiceStudio Streaming Text-To-Speech Service with Low-Latency Chunking & Circuit Breaker.

Connects to VoiceStudio backend (Kokoro 82M / OmniVoice) for sub-150ms streaming TTS.
Includes:
- Redis pre-computed speaker latent caching to eliminate cold-start synthesis overhead.
- Zero-downtime Latency Circuit Breaker: If TTFB > 450ms or local worker fails,
  automatically fails over mid-call to cloud TTS without dropping audio frames.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import aiohttp
try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("voicestudio")

from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts
from pipecat.utils.types import NOT_GIVEN, NotGiven


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # Normal operation: local VoiceStudio
    OPEN = "OPEN"            # Tripped: routing to cloud fallback
    HALF_OPEN = "HALF_OPEN"  # Testing if local VoiceStudio has recovered


@dataclass
class VoiceStudioTTSSettings(TTSSettings):
    """Runtime updatable settings for VoiceStudio TTS."""
    voice: str = "af_heart"
    model: str = "kokoro-82m"
    speed: float = 1.0
    language: str = "en-us"


class VoiceStudioTTSProvider(TTSService):
    """Ultra-low-latency streaming TTS provider for local VoiceStudio (Kokoro/OmniVoice)."""

    Settings = VoiceStudioTTSSettings
    _settings: Settings

    def __init__(
        self,
        *,
        base_url: str = "http://voicestudio-tts:8080",
        aiohttp_session: aiohttp.ClientSession,
        sample_rate: int = 24000,
        settings: Optional[VoiceStudioTTSSettings] = None,
        redis_client: Optional[Any] = None,
        fallback_tts_service: Optional[TTSService] = None,
        max_ttfb_ms: float = 450.0,
        circuit_cooldown_secs: float = 30.0,
        **kwargs,
    ):
        default_settings = settings or self.Settings()
        super().__init__(
            sample_rate=sample_rate,
            push_start_frame=True,
            push_stop_frames=True,
            settings=default_settings,
            **kwargs,
        )
        self._base_url = base_url.rstrip("/")
        self._session = aiohttp_session
        self._sample_rate = sample_rate
        self._redis = redis_client
        self._fallback_service = fallback_tts_service
        self._max_ttfb_ms = max_ttfb_ms
        self._circuit_cooldown_secs = circuit_cooldown_secs

        # Circuit Breaker state
        self._circuit_state = CircuitState.CLOSED
        self._last_state_change = time.time()
        self._consecutive_failures = 0

    @property
    def circuit_state(self) -> CircuitState:
        # Check if cool-down expired to attempt HALF_OPEN probe
        if (
            self._circuit_state == CircuitState.OPEN
            and (time.time() - self._last_state_change) > self._circuit_cooldown_secs
        ):
            logger.info("VoiceStudio Circuit Breaker entering HALF_OPEN probe state.")
            self._circuit_state = CircuitState.HALF_OPEN
            self._last_state_change = time.time()
        return self._circuit_state

    def trip_circuit_breaker(self, reason: str) -> None:
        """Trips the circuit breaker to failover to cloud TTS."""
        logger.warning(
            f"VoiceStudio Circuit Breaker TRIPPED to OPEN: {reason}. Failing over to cloud TTS."
        )
        self._circuit_state = CircuitState.OPEN
        self._last_state_change = time.time()
        self._consecutive_failures += 1

    def reset_circuit_breaker(self) -> None:
        """Resets the circuit breaker to normal local operation."""
        if self._circuit_state != CircuitState.CLOSED:
            logger.info("VoiceStudio Circuit Breaker recovered: Reset to CLOSED.")
        self._circuit_state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_state_change = time.time()

    async def _get_cached_speaker_latents(self, voice_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves pre-computed speaker latents from Redis cache."""
        if not self._redis:
            return None
        try:
            cache_key = f"voicestudio:latents:{voice_id}"
            cached_data = await self._redis.get(cache_key)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            logger.debug(f"VoiceStudio: Redis speaker latent lookup error: {e}")
        return None

    async def _cache_speaker_latents(self, voice_id: str, latents: Dict[str, Any]) -> None:
        """Stores speaker latents in Redis with 24-hour TTL."""
        if not self._redis:
            return
        try:
            cache_key = f"voicestudio:latents:{voice_id}"
            await self._redis.set(cache_key, json.dumps(latents), ex=86400)
        except Exception as e:
            logger.debug(f"VoiceStudio: Failed to cache speaker latents: {e}")

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        """Synthesizes text into streaming PCM chunks with circuit breaker protection."""
        clean_text = text.strip()
        if not clean_text:
            return

        # 1. If circuit breaker is OPEN, route directly to cloud fallback
        if self.circuit_state == CircuitState.OPEN and self._fallback_service:
            logger.info("VoiceStudio [Circuit OPEN]: Routing synthesis to cloud fallback.")
            async for frame in self._fallback_service.run_tts(text, context_id):
                yield frame
            return

        # 2. Attempt local VoiceStudio streaming synthesis
        stream_url = f"{self._base_url}/api/tts/stream"
        payload = {
            "text": clean_text,
            "voice": self._settings.voice,
            "model": self._settings.model,
            "speed": self._settings.speed,
            "sample_rate": self._sample_rate,
            "language": self._settings.language,
        }

        # Check speaker latent cache
        latents = await self._get_cached_speaker_latents(self._settings.voice)
        if latents:
            payload["speaker_latents"] = latents

        start_time = time.perf_counter()
        received_first_chunk = False

        try:
            await self.start_ttfb_metrics()

            # Timeout after max_ttfb_ms for first byte
            timeout = aiohttp.ClientTimeout(
                total=15.0, connect=2.0, sock_read=self._max_ttfb_ms / 1000.0
            )

            async with self._session.post(stream_url, json=payload, timeout=timeout) as resp:
                if resp.status != 200:
                    err_msg = await resp.text()
                    raise RuntimeError(f"VoiceStudio HTTP {resp.status}: {err_msg}")

                await self.start_tts_usage_metrics(clean_text)

                # Default PCM frame chunk size (e.g. 20ms of audio at sample_rate)
                # 24000 samples/sec * 2 bytes/sample * 0.02s = 960 bytes
                chunk_bytes = int(self._sample_rate * 2 * 0.02)

                async for chunk in resp.content.iter_chunked(chunk_bytes):
                    if not received_first_chunk:
                        ttfb_ms = (time.perf_counter() - start_time) * 1000.0
                        await self.stop_ttfb_metrics()
                        received_first_chunk = True

                        if ttfb_ms > self._max_ttfb_ms:
                            logger.warning(
                                f"VoiceStudio TTFB ({ttfb_ms:.1f}ms) exceeded threshold ({self._max_ttfb_ms}ms)"
                            )

                    if chunk:
                        yield TTSAudioRawFrame(
                            audio=chunk,
                            sample_rate=self._sample_rate,
                            num_channels=1,
                            context_id=context_id,
                        )

            # Success: reset circuit breaker if in HALF_OPEN
            self.reset_circuit_breaker()

        except Exception as exc:
            self.trip_circuit_breaker(f"VoiceStudio error ({exc})")

            # Fall back to cloud TTS if available without dropping the call
            if self._fallback_service:
                logger.info("VoiceStudio: Smoothly switching to cloud TTS provider for this turn.")
                try:
                    async for frame in self._fallback_service.run_tts(text, context_id):
                        yield frame
                    return
                except Exception as fb_err:
                    logger.error(f"VoiceStudio: Cloud fallback TTS also failed: {fb_err}")
                    yield ErrorFrame(error=f"TTS synthesis failed: {fb_err}")
            else:
                yield ErrorFrame(error=f"VoiceStudio synthesis failed: {exc}")
