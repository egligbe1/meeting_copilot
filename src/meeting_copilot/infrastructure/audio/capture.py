"""AudioCaptureManager + AudioThread — dual-stream audio capture.

Records microphone + system audio (WASAPI loopback on Windows, BlackHole
on macOS) simultaneously at 16 kHz.  Produces AudioChunkReady events every
15 seconds.
"""

from __future__ import annotations

import io
import logging
import struct
import threading
import wave
from typing import Any

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QThread

from meeting_copilot.application.event_bus import get_bus
from meeting_copilot.domain.events import AudioChunkReady, ErrorOccurred
from meeting_copilot.domain.settings import Settings

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000  # 16 kHz
CHANNELS = 1  # mono
CHUNK_DURATION_S = 15  # seconds per chunk
SILENCE_THRESHOLD = 0.003  # RMS below this is silence


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


class AudioThread(QThread):
    """Background QThread that captures audio and emits AudioChunkReady events.

    Opens up to two sounddevice input streams (microphone + loopback).
    Buffers 15 seconds, mixes, applies silence gate, and emits.
    """

    def __init__(
        self,
        settings: Settings,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._running = False

    def run(self) -> None:  # noqa: C901
        """Main capture loop — runs on a background thread."""
        self._running = True
        bus = get_bus()
        samples_per_chunk = SAMPLE_RATE * CHUNK_DURATION_S

        # Buffers
        mic_buffer: list[np.ndarray] = []
        loopback_buffer: list[np.ndarray] = []
        mic_lock = threading.Lock()
        loopback_lock = threading.Lock()

        has_loopback = False
        lb_rate = SAMPLE_RATE

        # --- Callbacks ---
        def mic_callback(indata, frames, time, status):
            if status: logger.debug("Mic status: %s", status)
            with mic_lock: mic_buffer.append(indata[:, 0].copy())

        def loopback_callback(indata, frames, time, status):
            if status: logger.debug("Loopback status: %s", status)
            with loopback_lock: loopback_buffer.append(indata[:, 0].copy())

        # Open Mic
        mic_stream = None
        try:
            mic_device = self._settings.mic_device_id
            mic_stream = sd.InputStream(
                device=mic_device, samplerate=SAMPLE_RATE, channels=CHANNELS,
                dtype="float32", callback=mic_callback, blocksize=SAMPLE_RATE
            )
            mic_stream.start()
            logger.info("Mic stream started (device=%s)", mic_device or "default")
        except Exception as exc:
            logger.exception("Failed to open mic")
            bus.emit(ErrorOccurred("audio_capture", f"Mic error: {exc}", False))
            return

        # Open Loopback
        loopback_stream = None
        try:
            lb_device = self._settings.loopback_device_id
            if lb_device is not None:
                # Try 16kHz first, if fails, query native rate
                try:
                    loopback_stream = sd.InputStream(
                        device=lb_device, samplerate=SAMPLE_RATE, channels=CHANNELS,
                        dtype="float32", callback=loopback_callback, blocksize=SAMPLE_RATE
                    )
                    loopback_stream.start()
                    lb_rate = SAMPLE_RATE
                except Exception:
                    # Fallback: Query native rate
                    dev_info = sd.query_devices(lb_device, 'input')
                    lb_rate = int(dev_info['default_samplerate'])
                    logger.info("Retrying loopback at native rate: %d Hz", lb_rate)
                    loopback_stream = sd.InputStream(
                        device=lb_device, samplerate=lb_rate, channels=CHANNELS,
                        dtype="float32", callback=loopback_callback, blocksize=lb_rate
                    )
                    loopback_stream.start()
                
                has_loopback = True
                logger.info("Loopback stream started (native rate: %d Hz)", lb_rate)
        except Exception as exc:
            logger.warning("Loopback failed: %s", exc)

        try:
            while self._running:
                self.msleep(CHUNK_DURATION_S * 1000)
                if not self._running: break

                # Drain and mix
                with mic_lock:
                    mic_audio = np.concatenate(mic_buffer) if mic_buffer else np.zeros(samples_per_chunk, dtype=np.float32)
                    mic_buffer.clear()
                
                lb_audio = None
                if has_loopback:
                    with loopback_lock:
                        if loopback_buffer:
                            lb_audio = np.concatenate(loopback_buffer)
                            loopback_buffer.clear()
                        else:
                            lb_audio = np.zeros(int(lb_rate * CHUNK_DURATION_S), dtype=np.float32)
                
                # Resample loopback if needed
                if lb_audio is not None and lb_rate != SAMPLE_RATE:
                    # Basic linear resampling for performance (whisper is resilient)
                    xp = np.linspace(0, CHUNK_DURATION_S, len(lb_audio))
                    x_new = np.linspace(0, CHUNK_DURATION_S, samples_per_chunk)
                    lb_audio = np.interp(x_new, xp, lb_audio).astype(np.float32)

                # Mix
                if lb_audio is not None:
                    min_len = min(len(mic_audio), len(lb_audio), samples_per_chunk)
                    mixed = (mic_audio[:min_len] + lb_audio[:min_len]) / 2.0
                else:
                    mixed = mic_audio[:samples_per_chunk]

                if _rms(mixed) < SILENCE_THRESHOLD: continue

                wav_bytes = _float32_to_wav_bytes(mixed)
                bus.emit(AudioChunkReady(audio=wav_bytes, length_ms=CHUNK_DURATION_S * 1000))

        finally:
            if mic_stream:
                mic_stream.stop()
                mic_stream.close()
            if loopback_stream:
                loopback_stream.stop()
                loopback_stream.close()
            logger.info("Audio capture stopped")

    def stop(self) -> None:
        """Signal the capture loop to stop."""
        self._running = False
        self.quit() # Stop the QThread event loop


class AudioCaptureManager:
    """Manages the AudioThread lifecycle."""

    def __init__(self) -> None:
        self._thread: AudioThread | None = None

    def start(self, settings: Settings, parent: QObject | None = None) -> None:
        """Start audio capture on a background thread."""
        if self._thread is not None and self._thread.isRunning():
            logger.warning("Audio capture already running")
            return

        self._thread = AudioThread(settings, parent=parent)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()
        logger.info("AudioCaptureManager started")

    def stop(self) -> None:
        """Stop audio capture gracefully."""
        if self._thread is not None and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait(5000)  # wait up to 5 seconds
            logger.info("AudioCaptureManager stopped")
        self._thread = None
