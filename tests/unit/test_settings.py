"""Tests for domain.settings and infrastructure.persistence.config."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from meeting_copilot.domain.settings import Settings
from meeting_copilot.infrastructure.persistence.config import ConfigStore


class TestSettings:
    """Settings dataclass behavior."""

    def test_defaults(self) -> None:
        s = Settings()
        assert s.mic_device_id is None
        assert s.loopback_device_id == -1
        assert s.groq_model_stt == "whisper-large-v3-turbo"
        assert s.groq_model_llm == "openai/gpt-oss-20b"
        assert s.word_trigger == 55
        assert s.context_window_minutes == 10
        assert s.overlay_x == -1
        assert s.overlay_y == -1
        assert s.overlay_opacity == 0.92
        assert s.meeting_context == ""
        assert s.interview_focus == "data_engineering"

    def test_immutability(self) -> None:
        s = Settings()
        with pytest.raises(FrozenInstanceError):
            s.word_trigger = 100  # type: ignore[misc]

    def test_custom_values(self) -> None:
        s = Settings(
            mic_device_id=2,
            word_trigger=120,
            meeting_context="budget review",
        )
        assert s.mic_device_id == 2
        assert s.word_trigger == 120
        assert s.meeting_context == "budget review"
        # Other fields still have defaults
        assert s.overlay_opacity == 0.92


class TestConfigStore:
    """ConfigStore load/save roundtrip."""

    def test_load_returns_defaults_when_no_file(self, tmp_path: Path) -> None:
        with patch(
            "meeting_copilot.infrastructure.persistence.config._config_path",
            return_value=tmp_path / "config.json",
        ):
            store = ConfigStore()
            settings = store.load()

        assert settings == Settings()

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        with patch(
            "meeting_copilot.infrastructure.persistence.config._config_path",
            return_value=config_file,
        ), patch(
            "meeting_copilot.infrastructure.persistence.config._config_dir",
            return_value=tmp_path,
        ):
            store = ConfigStore()
            original = Settings(
                mic_device_id=3,
                word_trigger=100,
                overlay_opacity=0.85,
                meeting_context="sprint retro",
            )
            store.save(original)
            loaded = store.load()

        assert loaded == original

    def test_load_ignores_unknown_keys(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"word_trigger": 60, "unknown_key": "value"}),
            encoding="utf-8",
        )
        with patch(
            "meeting_copilot.infrastructure.persistence.config._config_path",
            return_value=config_file,
        ):
            store = ConfigStore()
            settings = store.load()

        assert settings.word_trigger == 60

    def test_load_handles_corrupt_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("not json!!", encoding="utf-8")
        with patch(
            "meeting_copilot.infrastructure.persistence.config._config_path",
            return_value=config_file,
        ):
            store = ConfigStore()
            settings = store.load()

        assert settings == Settings()

    def test_load_migrates_unavailable_llm_model(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {"groq_model_llm": "meta-llama/llama-4-scout-17b-16e-instruct"}
            ),
            encoding="utf-8",
        )
        with patch(
            "meeting_copilot.infrastructure.persistence.config._config_path",
            return_value=config_file,
        ):
            settings = ConfigStore().load()

        assert settings.groq_model_llm == "openai/gpt-oss-20b"
