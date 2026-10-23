"""AudioCaptureManager + AudioThread — system-audio speech capture.

Captures only system audio (WASAPI loopback on Windows, BlackHole on macOS)
at 16 kHz. Microphone input is never sent for transcription.
Emits speech segments after a brief pause.
"""

from __future__ import annotations

import io
import logging
import threading
import wave
from collections import deque
from typing import Any

import numpy as np
import sounddevice as sd  # type: ignore[import-untyped]
from PySide6.QtCore import QObject, QThread

from meeting_copilot.application.event_bus import get_bus
from meeting_copilot.domain.events import AudioChunkReady, ErrorOccurred
from meeting_copilot.domain.settings import Settings
from meeting_copilot.infrastructure.audio.devices import find_best_loopback

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000  # 16 kHz
CHANNELS = 1  # mono
SILENCE_THRESHOLD = 0.005
POLL_INTERVAL_MS = 100
END_OF_SPEECH_S = 0.8
PRE_ROLL_S = 0.2
MAX_SEGMENT_S = 30


def _float32_to_wav_bytes(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Convert float32 mono audio to 16-bit PCM WAV bytes."""
    # Clip and convert to 16-bit int
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())

    return buf.getvalue()


def _rms(audio: np.ndarray) -> float:
    """Compute the root-mean-square amplitude of an audio array."""
    if len(audio) == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio**2)))


class _SpeechSegmenter:
    """Collect audio into segments and close them after a short pause."""

    def __init__(self) -> None:
        self._pre_roll: deque[np.ndarray] = deque()
        self._pre_roll_samples = 0
        self._frames: list[np.ndarray] = []
        self._sample_count = 0
        self._silence_samples = 0

    def add(self, audio: np.ndarray) -> np.ndarray | None:
        """Add one audio frame and return a completed speech segment, if any."""
        voiced = _rms(audio) >= SILENCE_THRESHOLD
        if self._frames:
            self._frames.append(audio)
            self._sample_count += len(audio)
            self._silence_samples = (
                0 if voiced else self._silence_samples + len(audio)
            )
            if (
                self._silence_samples >= SAMPLE_RATE * END_OF_SPEECH_S
                or self._sample_count >= SAMPLE_RATE * MAX_SEGMENT_S
            ):
                frames = self._frames
                sample_count = self._sample_count
                self._reset()
                return np.concatenate(frames) if sample_count >= SAMPLE_RATE // 4 else None
        elif voiced:
            self._frames = [*self._pre_roll, audio]
            self._sample_count = self._pre_roll_samples + len(audio)
            self._pre_roll.clear()
            self._pre_roll_samples = 0
        else:
            self._pre_roll.append(audio)
            self._pre_roll_samples += len(audio)
            while self._pre_roll_samples > SAMPLE_RATE * PRE_ROLL_S:
                removed = self._pre_roll.popleft()
                self._pre_roll_samples -= len(removed)
        return None

    def _reset(self) -> None:
        self._pre_roll.clear()
        self._pre_roll_samples = 0
        self._frames = []
        self._sample_count = 0
        self._silence_samples = 0

    def clear(self) -> None:
        """Discard any partial utterance and retained pre-roll."""
        self._reset()


class AudioThread(QThread):
    """Capture system audio and emit speech segments for transcription.

    Opens only the selected loopback input. No microphone stream is opened.
    """

    def __init__(
        self,
        settings: Settings,
        parent: Any = None,
        context_generation: int = 0,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._running = False
        self._context_generation = context_generation
        self._context_lock = threading.Lock()

    def set_context_generation(self, generation: int) -> None:
        """Mark buffered and future audio with the new context generation."""
        with self._context_lock:
            self._context_generation = generation

    def run(self) -> None:  # noqa: C901 — complexity acceptable for audio loop
        """Main capture loop — runs on a background thread."""
        self._running = True
        bus = get_bus()
        poll_samples = SAMPLE_RATE * POLL_INTERVAL_MS // 1000

        loopback_buffer: list[np.ndarray] = []
        loopback_lock = threading.Lock()
        segmenter = _SpeechSegmenter()
        active_generation = self._context_generation

        def loopback_callback(
            indata: np.ndarray,
            frames: int,
            time_info: Any,
            status: sd.CallbackFlags,
        ) -> None:
            if status:
                logger.debug("Loopback stream status: %s", status)
            with loopback_lock:
                loopback_buffer.append(indata[:, 0].copy())

        def open_input_stream(
            device_id: int, callback_fn: Any
        ) -> tuple[sd.InputStream, int]:
            """Try to open a stream at native rate, or fall back to 16k/44.1k/48k."""
            info = sd.query_devices(device_id, "input")
            native_rate = (
                int(info.get("default_samplerate", SAMPLE_RATE))
                if info
                else SAMPLE_RATE
            )

            rates_to_try = [native_rate, 44100, 48000, 16000]
            if native_rate in rates_to_try:
                rates_to_try.remove(native_rate)
            rates_to_try.insert(0, native_rate)

            last_exc = None
            for rate in rates_to_try:
                try:
                    stream = sd.InputStream(
                        device=device_id,
                        samplerate=rate,
                        channels=CHANNELS,
                        dtype="float32",
                        callback=callback_fn,
                        blocksize=0,
                    )
                    return stream, rate
                except Exception as e:
                    last_exc = e
                    continue
            raise last_exc or Exception("Could not open stream at any rate")

        # Resolve only the system-audio input; never fall back to the mic.
        loopback_stream = None
        try:
            lb_device = self._settings.loopback_device_id
            if lb_device == -1:
                lb_info = find_best_loopback()
                if lb_info:
                    lb_device = lb_info["id"]
                    logger.info(
                        "Auto-resolved system audio to: %s (API: %s)",
                        lb_info["name"],
                        lb_info["host_api"],
                    )
                else:
                    lb_device = None

            if lb_device is None:
                raise RuntimeError(
                    "No system-audio input is selected. Select BlackHole (macOS) "
                    "or a loopback device in Settings → Audio. Microphone audio "
                    "is not used for transcription."
                )

            loopback_stream, lb_native_rate = open_input_stream(
                lb_device, loopback_callback
            )
            loopback_stream.start()
            logger.info(
                "System-audio stream started (device=%s, rate=%d)",
                lb_device,
                lb_native_rate,
            )
        except Exception as exc:
            logger.warning(
                "System-audio input unavailable (device=%s)",
                self._settings.loopback_device_id,
            )
            bus.emit(
                ErrorOccurred(
                    source="audio_capture",
                    message=str(exc),
                    recoverable=True,
                )
            )
            return

        def resample(audio: np.ndarray, source_rate: int) -> np.ndarray:
            if len(audio) == 0 or source_rate == SAMPLE_RATE:
                return audio
            target_samples = max(1, round(len(audio) * SAMPLE_RATE / source_rate))
            source_positions = np.arange(len(audio)) / source_rate
            target_positions = np.arange(target_samples) / SAMPLE_RATE
            return np.asarray(
                np.interp(target_positions, source_positions, audio),
                dtype=np.float32,
            )

        def emit_segment(audio: np.ndarray, generation: int) -> None:
            peak = float(np.max(np.abs(audio)))
            if peak > 0:
                audio = audio * (0.95 / peak)
            wav_bytes = _float32_to_wav_bytes(audio)
            bus.emit(
                AudioChunkReady(
                    audio=wav_bytes,
                    length_ms=round(len(audio) * 1000 / SAMPLE_RATE),
                    context_generation=generation,
                )
            )
            logger.debug(
                "Emitted speech segment (%d ms, %d bytes)",
                round(len(audio) * 1000 / SAMPLE_RATE),
                len(wav_bytes),
            )

        # Capture loop
        try:
            while self._running:
                self.msleep(POLL_INTERVAL_MS)

                if not self._running:
                    break

                with self._context_lock:
                    context_generation = self._context_generation
                if context_generation != active_generation:
                    segmenter.clear()
                    with loopback_lock:
                        loopback_buffer.clear()
                    active_generation = context_generation

                with loopback_lock:
                    if loopback_buffer:
                        raw_audio = np.concatenate(loopback_buffer)
                        loopback_buffer.clear()
                    else:
                        raw_audio = np.zeros(0, dtype=np.float32)

                system_audio = resample(raw_audio, lb_native_rate)
                if len(system_audio) == 0:
                    system_audio = np.zeros(poll_samples, dtype=np.float32)

                completed_segment = segmenter.add(system_audio)
                if completed_segment is not None:
                    emit_segment(completed_segment, active_generation)

        finally:
            if loopback_stream is not None:
                loopback_stream.stop()
                loopback_stream.close()
            logger.info("Audio capture stopped")

    def stop(self) -> None:
        """Signal the capture loop to stop."""
        self._running = False


class AudioCaptureManager:
    """Manages the AudioThread lifecycle."""

    def __init__(self) -> None:
        self._thread: AudioThread | None = None
        self._context_generation = 0

    def start(self, settings: Settings, parent: QObject | None = None) -> None:
        """Start audio capture on a background thread."""
        if self._thread is not None and self._thread.isRunning():
            logger.warning("Audio capture already running")
            return

        self._thread = AudioThread(
            settings,
            parent=parent,
            context_generation=self._context_generation,
        )
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()
        logger.info("AudioCaptureManager started")

    def stop(self) -> None:
        """Stop audio capture gracefully."""
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.stop()
                if not self._thread.wait(5000):
                    logger.warning("AudioThread did not stop gracefully; forcing.")
            
            # Important: set to None only after wait() completes
            # to avoid premature destruction of the wrapper object
            self._thread = None
            logger.info("AudioCaptureManager stopped")

    def clear_context(self, generation: int) -> None:
        """Invalidate buffered audio and tag future capture with *generation*."""
        self._context_generation = generation
        if self._thread is not None and self._thread.isRunning():
            self._thread.set_context_generation(generation)
