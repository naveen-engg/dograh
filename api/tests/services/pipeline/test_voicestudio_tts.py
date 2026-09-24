import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.services.pipecat.voicestudio_tts import (
    CircuitState,
    VoiceStudioTTSProvider,
    VoiceStudioTTSSettings,
)
from pipecat.frames.frames import TTSAudioRawFrame


@pytest.mark.asyncio
async def test_voicestudio_circuit_breaker_trips_to_open_on_error():
    mock_session = MagicMock()
    mock_fallback = MagicMock()

    # Configure fallback mock generator
    async def mock_fallback_run_tts(text, context_id):
        yield TTSAudioRawFrame(
            audio=b"\x00\x00" * 480,
            sample_rate=24000,
            num_channels=1,
            context_id=context_id,
        )

    mock_fallback.run_tts = mock_fallback_run_tts

    # Configure session.post to simulate local failure (e.g. connection refused)
    mock_session.post.side_effect = RuntimeError("Connection to VoiceStudio worker refused")

    provider = VoiceStudioTTSProvider(
        base_url="http://localhost:8080",
        aiohttp_session=mock_session,
        sample_rate=24000,
        settings=VoiceStudioTTSSettings(voice="af_heart"),
        fallback_tts_service=mock_fallback,
        max_ttfb_ms=450.0,
    )

    assert provider.circuit_state == CircuitState.CLOSED

    # Synthesize text: should fail locally and cleanly yield from fallback
    frames = []
    async for frame in provider.run_tts("Hello from VoiceStudio", "ctx_1"):
        frames.append(frame)

    # Verify circuit breaker tripped
    assert provider.circuit_state == CircuitState.OPEN
    # Verify fallback yielded audio frame without crashing
    assert len(frames) == 1
    assert isinstance(frames[0], TTSAudioRawFrame)


@pytest.mark.asyncio
async def test_voicestudio_redis_speaker_latent_caching():
    mock_session = MagicMock()
    mock_redis = AsyncMock()

    # Mock Redis returning cached latents
    mock_redis.get.return_value = '{"speaker_embedding": [0.1, 0.2, 0.3]}'

    provider = VoiceStudioTTSProvider(
        base_url="http://localhost:8080",
        aiohttp_session=mock_session,
        redis_client=mock_redis,
    )

    latents = await provider._get_cached_speaker_latents("af_heart")
    assert latents is not None
    assert latents["speaker_embedding"] == [0.1, 0.2, 0.3]
    mock_redis.get.assert_called_once_with("voicestudio:latents:af_heart")
