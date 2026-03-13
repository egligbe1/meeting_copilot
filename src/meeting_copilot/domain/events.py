"""All EventBus event dataclasses — frozen, immutable, type-annotated.

Events are plain data bags with no methods. They serve as the typed
communication protocol between all layers of the application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class AudioChunkReady:
    """Emitted by AudioThread when a 15-second audio chunk is captured."""

    audio: bytes  # 16-bit PCM, 16 kHz, mono (WAV bytes)
    length_ms: int


@dataclass(frozen=True)
class TranscriptSegmentAdded:
    """Emitted by GroqSTTClient when a chunk is transcribed."""

    timestamp: datetime
    speaker: str  # 'You' | 'Meeting'
    text: str


@dataclass(frozen=True)
class QuestionsReady:
    """Emitted by GroqLLMClient with AI-generated questions."""

    questions: tuple[str, ...]
    context_word_count: int


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


@dataclass(frozen=True)
class SessionSummaryReady:
    """Emitted by GroqLLMClient with the final post-meeting summary."""

    summary_md: str
