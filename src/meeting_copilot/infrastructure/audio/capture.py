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
from PySide6.QtCore import QObject, QThread

from meeting_copilot.application.event_bus import get_bus
from meeting_copilot.domain.events import AudioChunkReady, ErrorOccurred
from meeting_copilot.domain.settings import Settings
from meeting_copilot.infrastructure.audio.devices import find_best_loopback, list_devices

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000  # 16 kHz
CHANNELS = 1  # mono
CHUNK_DURATION_S = 10  # seconds per chunk
SILENCE_THRESHOLD = 0.001  # Lowered: RMS below this is silence


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

    def run(self) -> None:  # noqa: C901 — complexity acceptable for audio loop
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

        # --- Mic callback ---
        def mic_callback(
            indata: np.ndarray,
            frames: int,
            time_info: Any,
            status: sd.CallbackFlags,
        ) -> None:
            if status:
                logger.debug("Mic stream status: %s", status)
            with mic_lock:
                mic_buffer.append(indata[:, 0].copy())

        # --- Loopback callback ---
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

        def open_input_stream(device_id: int | None, callback_fn: Any) -> tuple[sd.InputStream, int]:
            """Try to open a stream at native rate, or fall back to 16k/44.1k/48k."""
            info = sd.query_devices(device_id, "input")
            native_rate = int(info.get("default_samplerate", SAMPLE_RATE)) if info else SAMPLE_RATE
            
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
                        blocksize=0  # PortAudio decides optimal size
                    )
                    return stream, rate
                except Exception as e:
                    last_exc = e
                    continue
            raise last_exc or Exception("Could not open stream at any rate")

        # Open streams
        mic_stream = None
        loopback_stream = None

        try:
            mic_device = self._settings.mic_device_id
            mic_stream, mic_native_rate = open_input_stream(mic_device, mic_callback)
            mic_stream.start()
            logger.info(
                "Mic stream started (device=%s, rate=%d)", 
                mic_device if mic_device is not None else "default", mic_native_rate
            )
        except Exception as exc:
            logger.exception("Failed to open mic stream")
            bus.emit(
                ErrorOccurred(
                    source="audio_capture",
                    message=f"Mic stream error: {exc}",
                    recoverable=False,
                )
            )
            return

        try:
            lb_device = self._settings.loopback_device_id
            if lb_device == -1:
                # Resolve Auto loopback with heuristics
                lb_info = find_best_loopback()
                if lb_info:
                    lb_device = lb_info["id"]
                    logger.info("Auto-resolved loopback to: %s (API: %s)", lb_info["name"], lb_info["host_api"])
                else:
                    lb_device = None

            if lb_device is not None:
                # Attempt to open loopback. If it's a candidate list, we might try others, 
                # but for now we follow find_best_loopback suggestion.
                # If it fails, we catch it and log a warning.
                try:
                    loopback_stream, lb_native_rate = open_input_stream(lb_device, loopback_callback)
                    loopback_stream.start()
                    has_loopback = True
                    logger.info(
                        "Loopback stream started (device=%s, rate=%d)", 
                        lb_device, lb_native_rate
                    )
                except Exception as inner_exc:
                    logger.warning("Failed to open resolved loopback %s: %s", lb_device, inner_exc)
                    # If it was an auto-res, we could try falling back to the next candidate
                    # but find_best_loopback already picked the best.
                    raise inner_exc
        except Exception as exc:
            logger.warning(
                "Loopback unavailable (device=%s): %s — using mic only",
                self._settings.loopback_device_id,
                exc,
            )
            bus.emit(
                ErrorOccurred(
                    source="audio_capture",
                    message=f"Loopback unavailable: {exc}",
                    recoverable=True,
                )
            )

        # Capture loop
        try:
            while self._running:
                # Sleep for chunk duration
                self.msleep(CHUNK_DURATION_S * 1000)

                if not self._running:
                    break

                # Drain mic buffer
                with mic_lock:
                    if mic_buffer:
                        raw_mic_audio = np.concatenate(mic_buffer)
                        mic_buffer.clear()
                    else:
                        raw_mic_audio = np.zeros(0, dtype=np.float32)

                # Resample mic if needed
                if len(raw_mic_audio) > 0 and mic_native_rate != SAMPLE_RATE:
                    duration = len(raw_mic_audio) / mic_native_rate
                    new_samples = int(duration * SAMPLE_RATE)
                    x_old = np.linspace(0, duration, len(raw_mic_audio))
                    x_new = np.linspace(0, duration, new_samples)
                    mic_audio = np.interp(x_new, x_old, raw_mic_audio).astype(np.float32)
                elif len(raw_mic_audio) > 0:
                    mic_audio = raw_mic_audio
                else:
                    mic_audio = np.zeros(samples_per_chunk, dtype=np.float32)

                # Drain and resample loopback buffer
                if has_loopback:
                    with loopback_lock:
                        if loopback_buffer:
                            raw_lb_audio = np.concatenate(loopback_buffer)
                            loopback_buffer.clear()
                        else:
                            raw_lb_audio = np.zeros(0, dtype=np.float32)
                    
                    if len(raw_lb_audio) > 0 and lb_native_rate != SAMPLE_RATE:
                        duration = len(raw_lb_audio) / lb_native_rate
                        new_samples = int(duration * SAMPLE_RATE)
                        x_old = np.linspace(0, duration, len(raw_lb_audio))
                        x_new = np.linspace(0, duration, new_samples)
                        lb_audio = np.interp(x_new, x_old, raw_lb_audio).astype(np.float32)
                    elif len(raw_lb_audio) > 0:
                        lb_audio = raw_lb_audio
                    else:
                        lb_audio = np.zeros(samples_per_chunk, dtype=np.float32)
                else:
                    lb_audio = None

                # Mix
                if lb_audio is not None:
                    # Match lengths
                    min_len = min(len(mic_audio), len(lb_audio))
                    # Additive mixing (sum) instead of averaging to keep signals strong
                    mixed = mic_audio[:min_len] + lb_audio[:min_len]
                else:
                    mixed = mic_audio

                # Peak Normalization: scale so max absolute amplitude is 0.95
                # This ensures the STT engine gets a strong, consistent signal.
                max_val = np.max(np.abs(mixed))
                if max_val > 0:
                    mixed = mixed * (0.95 / max_val)

                # Silence gate
                if _rms(mixed) < SILENCE_THRESHOLD:
                    logger.debug("Chunk below silence threshold — skipping")
                    continue

                # Convert to WAV bytes and emit
                wav_bytes = _float32_to_wav_bytes(mixed)
                bus.emit(
                    AudioChunkReady(
                        audio=wav_bytes,
                        length_ms=CHUNK_DURATION_S * 1000,
                    )
                )
                logger.debug("Emitted AudioChunkReady (%d bytes)", len(wav_bytes))

        finally:
            if mic_stream is not None:
                mic_stream.stop()
                mic_stream.close()
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
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.stop()
                if not self._thread.wait(5000):
                    logger.warning("AudioThread did not stop gracefully; forcing.")
            
            # Important: set to None only after wait() completes
            # to avoid premature destruction of the wrapper object
            self._thread = None
            logger.info("AudioCaptureManager stopped")
