"""GroqSTTClient — Speech-to-text via Groq Whisper API.

Wraps ``groq.audio.transcriptions.create()``.  Called from
TranscriptionWorker on a QThread.  Emits TranscriptSegmentAdded or
ErrorOccurred via the EventBus.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime

from groq import Groq, RateLimitError

from meeting_copilot.application.event_bus import get_bus
from meeting_copilot.domain.events import (
    ApiRateLimited,
    ErrorOccurred,
    TranscriptSegmentAdded,
)
from meeting_copilot.domain.settings import Settings

logger = logging.getLogger(__name__)


class GroqSTTClient:
    """Send audio chunks to Groq Whisper and emit transcript events."""

    def __init__(self, settings: Settings, api_key: str) -> None:
        self._settings = settings
        self._client = Groq(api_key=api_key)

    def transcribe(self, audio_bytes: bytes, speaker: str = "Meeting") -> None:
        """Transcribe *audio_bytes* (WAV) and emit a TranscriptSegmentAdded.

        Parameters
        ----------
        audio_bytes:
            Complete WAV file bytes (16-bit PCM, 16 kHz, mono).
        speaker:
            Label for the speaker — ``'You'`` or ``'Meeting'``.
        """
        bus = get_bus()

        try:
            # Write to a temporary WAV file for the Groq API
            with tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False
            ) as fp:
                fp.write(audio_bytes)
                fp.flush()
                temp_path = fp.name

            with open(temp_path, "rb") as audio_file:
                response = self._client.audio.transcriptions.create(
                    model=self._settings.groq_model_stt,
                    file=audio_file,
                    response_format="text",
                )

            text = str(response).strip()
            if not text:
                logger.debug("Empty transcription — skipping")
                return

            bus.emit(
                TranscriptSegmentAdded(
                    timestamp=datetime.now(),
                    speaker=speaker,
                    text=text,
                )
            )
            logger.debug("Transcribed %d chars from %s", len(text), speaker)

        except RateLimitError as exc:
            retry_after = int(
                getattr(exc.response, "headers", {}).get("retry-after", 30)
            )
            bus.emit(
                ApiRateLimited(
                    service="groq_stt", retry_after_seconds=retry_after
                )
            )
            logger.warning("STT rate limited — retry after %ds", retry_after)

        except Exception as exc:
            bus.emit(
                ErrorOccurred(
                    source="groq_stt",
                    message=str(exc),
                    recoverable=True,
                )
            )
            logger.exception("STT transcription error")
