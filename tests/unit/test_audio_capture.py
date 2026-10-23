"""Tests for pause-based audio speech segmentation."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import numpy as np
import pytest

from meeting_copilot.domain.events import AudioChunkReady, ErrorOccurred
from meeting_copilot.domain.settings import Settings
from meeting_copilot.infrastructure.audio.capture import (
    END_OF_SPEECH_S,
    POLL_INTERVAL_MS,
    SAMPLE_RATE,
    SILENCE_THRESHOLD,
    AudioThread,
    _SpeechSegmenter,
)


def test_segmenter_waits_for_end_of_speech_silence() -> None:
    segmenter = _SpeechSegmenter()
    speech = np.full(SAMPLE_RATE * POLL_INTERVAL_MS // 1000, 0.1, dtype=np.float32)
    silence = np.zeros_like(speech)

    segmenter.add(silence)
    segmenter.add(silence)
    assert segmenter.add(speech) is None
    for _ in range(int(END_OF_SPEECH_S * 1000 / POLL_INTERVAL_MS) - 1):
        assert segmenter.add(silence) is None

    completed = segmenter.add(silence)

    assert completed is not None
    assert len(completed) >= SAMPLE_RATE * END_OF_SPEECH_S


def test_segmenter_keeps_speech_open_when_audio_resumes() -> None:
    segmenter = _SpeechSegmenter()
    speech = np.full(SAMPLE_RATE * POLL_INTERVAL_MS // 1000, 0.1, dtype=np.float32)
    silence = np.zeros_like(speech)

    segmenter.add(silence)
    segmenter.add(silence)
    segmenter.add(speech)
    for _ in range(int(END_OF_SPEECH_S * 1000 / POLL_INTERVAL_MS) - 1):
        assert segmenter.add(silence) is None
    assert segmenter.add(speech) is None

    for _ in range(int(END_OF_SPEECH_S * 1000 / POLL_INTERVAL_MS)):
        completed = segmenter.add(silence)

    assert completed is not None
    assert len(completed) > SAMPLE_RATE * END_OF_SPEECH_S


def test_segmenter_treats_low_level_background_noise_as_silence() -> None:
    segmenter = _SpeechSegmenter()
    speech = np.full(SAMPLE_RATE // 10, 0.1, dtype=np.float32)
    background_noise = np.full(
        SAMPLE_RATE // 10, SILENCE_THRESHOLD / 2, dtype=np.float32
    )

    segmenter.add(np.zeros_like(speech))
    segmenter.add(np.zeros_like(speech))
    segmenter.add(speech)
    completed = None
    for _ in range(int(END_OF_SPEECH_S * 10)):
        completed = segmenter.add(background_noise)

    assert completed is not None


def test_segmenter_clear_discards_partial_old_question() -> None:
    segmenter = _SpeechSegmenter()
    speech = np.full(SAMPLE_RATE // 10, 0.1, dtype=np.float32)
    silence = np.zeros_like(speech)

    segmenter.add(speech)
    segmenter.clear()

    for _ in range(int(END_OF_SPEECH_S * 10)):
        assert segmenter.add(silence) is None


def test_audio_thread_opens_only_system_audio_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread = AudioThread(Settings(mic_device_id=2, loopback_device_id=7))
    emitted: list[object] = []
    bus = Mock()
    bus.emit.side_effect = emitted.append
    monkeypatch.setattr(
        "meeting_copilot.infrastructure.audio.capture.get_bus", lambda: bus
    )

    class FakeStream:
        def __init__(self, **kwargs: Any) -> None:
            self.device = kwargs["device"]
            self.callback = kwargs["callback"]

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    streams: list[FakeStream] = []

    def make_stream(**kwargs: Any) -> FakeStream:
        stream = FakeStream(**kwargs)
        streams.append(stream)
        return stream

    monkeypatch.setattr(
        "meeting_copilot.infrastructure.audio.capture.sd.query_devices",
        lambda *_args: {"default_samplerate": SAMPLE_RATE},
    )
    monkeypatch.setattr(
        "meeting_copilot.infrastructure.audio.capture.sd.InputStream", make_stream
    )

    polls = 0

    def fake_sleep(_milliseconds: int) -> None:
        nonlocal polls
        polls += 1
        frame = (
            np.full((SAMPLE_RATE // 10, 1), 0.1, dtype=np.float32)
            if polls == 1
            else np.zeros((SAMPLE_RATE // 10, 1), dtype=np.float32)
        )
        streams[0].callback(frame, len(frame), None, None)
        if polls == 10:
            thread.stop()

    monkeypatch.setattr(AudioThread, "msleep", staticmethod(fake_sleep))

    thread.run()

    assert len(streams) == 1
    assert streams[0].device == 7
    assert any(isinstance(event, AudioChunkReady) for event in emitted)


def test_audio_thread_does_not_fall_back_to_microphone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread = AudioThread(Settings(mic_device_id=2, loopback_device_id=None))
    emitted: list[object] = []
    bus = Mock()
    bus.emit.side_effect = emitted.append
    monkeypatch.setattr(
        "meeting_copilot.infrastructure.audio.capture.get_bus", lambda: bus
    )
    input_stream = Mock()
    monkeypatch.setattr(
        "meeting_copilot.infrastructure.audio.capture.sd.InputStream",
        input_stream,
    )

    thread.run()

    input_stream.assert_not_called()
    assert any(
        isinstance(event, ErrorOccurred) and "system-audio input" in event.message
        for event in emitted
    )
