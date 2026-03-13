"""Settings dataclass — frozen, loaded from config.json by ConfigStore.

A new instance is created on each save; never mutated in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    """All user-configurable settings for Meeting Co-Pilot."""

    # Audio
    mic_device_id: int | None = field(default=None)
    loopback_device_id: int | None = field(default=None)

    # Transcription
    groq_model_stt: str = field(default="whisper-large-v3-turbo")

    # LLM
    groq_model_llm: str = field(
        default="llama-3.3-70b-versatile"
    )
    word_trigger: int = field(default=40)  # words before LLM call
    context_window_minutes: int = field(default=3)

    # UI
    overlay_x: int = field(default=-1)  # -1 = auto bottom-right
    overlay_y: int = field(default=-1)
    overlay_opacity: float = field(default=0.92)

    # Meta
    meeting_context: str = field(default="")  # optional freetext
