"""All EventBus event dataclasses — frozen, immutable, type-annotated.

Events are plain data bags with no methods. They serve as the typed
communication protocol between all layers of the application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class AudioChunkReady:
    """Emitted by AudioThread when a system-audio speech segment is captured."""

    audio: bytes  # 16-bit PCM, 16 kHz, mono (WAV bytes)
    length_ms: int
    context_generation: int = 0


@dataclass(frozen=True)
class ClearContextRequested:
    """Emitted when the user starts a fresh interview-question context."""


@dataclass(frozen=True)
class ContextCleared:
    """Emitted after the current transcript and pending audio are invalidated."""

    generation: int


@dataclass(frozen=True)
class TranscriptSegmentAdded:
    """Emitted by GroqSTTClient when a chunk is transcribed."""

    timestamp: datetime
    speaker: str  # 'You' | 'Meeting'
    text: str
    context_generation: int = 0


@dataclass(frozen=True)
class AnswerReady:
    """Emitted by GroqLLMClient with interview-ready answer guidance."""

    answer: str
    talking_points: tuple[str, ...]
    follow_up: str | None
    context_word_count: int
    context_generation: int = 0


@dataclass(frozen=True)
class ListeningStateChanged:
    """Emitted by Orchestrator when capture starts or stops."""

    is_listening: bool


@dataclass(frozen=True)
class ApiRateLimited:
    """Emitted when a Groq API call hits the rate limit."""

    service: str  # 'groq_stt' | 'groq_llm'
    retry_after_seconds: int


@dataclass(frozen=True)
class ErrorOccurred:
    """Emitted when a recoverable or fatal error occurs."""

    source: str  # e.g. 'groq_stt', 'groq_llm', 'audio_capture'
    message: str
    recoverable: bool = field(default=True)


@dataclass(frozen=True)
class SettingsChanged:
    """Emitted when a user setting is modified via the Settings dialog."""

    key: str
    value: object
