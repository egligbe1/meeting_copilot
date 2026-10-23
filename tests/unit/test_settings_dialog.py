"""Tests for audio-source choices in the settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from meeting_copilot.domain.settings import Settings
from meeting_copilot.ui.settings_dialog import SettingsDialog


def test_audio_settings_expose_system_audio_without_microphone_choice(
    qtbot: QtBot,
) -> None:
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    labels = [label.text() for label in dialog.findChildren(QLabel)]

    assert not hasattr(dialog, "combo_mic")
    assert "System Audio (Loopback):" in labels
    assert any("microphone is never included" in label for label in labels)
