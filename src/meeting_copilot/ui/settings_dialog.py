"""SettingsDialog — 3-tab modal dialog for configuring the app.

Tabs:
    * API — Groq API key with validation.
    * Audio — Input device selection (mic + loopback).
    * Preferences — LLM word triggers, context window, overlay opacity.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from meeting_copilot.application.event_bus import get_bus
from meeting_copilot.domain.events import SettingsChanged
from meeting_copilot.domain.settings import Settings
from meeting_copilot.infrastructure.audio.devices import list_devices
from meeting_copilot.infrastructure.persistence.config import ConfigStore

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Configuration dialog with tabs for API, Audio, and Preferences."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Meeting Co-Pilot Settings")
        self.setMinimumWidth(450)
        self._settings = settings
        self._config_store = ConfigStore()

        self.init_ui()

    def init_ui(self) -> None:
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 16, 16, 16)
        self.layout.setSpacing(20)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_api_tab(), "API")
        self.tabs.addTab(self._build_audio_tab(), "Audio")
        self.tabs.addTab(self._build_prefs_tab(), "Preferences")
        self.layout.addWidget(self.tabs)

        # Bottom Buttons
        self.buttons = QHBoxLayout()
        self.btn_save = QPushButton("Save & Close")
        self.btn_save.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("background-color: #374151;")
        self.btn_cancel.clicked.connect(self.reject)

        self.buttons.addStretch()
        self.buttons.addWidget(self.btn_cancel)
        self.buttons.addWidget(self.btn_save)
        self.layout.addLayout(self.buttons)

    # --- Tab Builders ---

    def _build_api_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<b>Groq Cloud API Key</b>"))
        self.edit_api_key = QLineEdit()
        self.edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_api_key.setPlaceholderText("gsk_...")
        
        # Load from keyring
        api_key = self._config_store.get_api_key()
        if api_key:
            self.edit_api_key.setText(api_key)
            
        layout.addWidget(self.edit_api_key)

        self.lbl_api_status = QLabel("API key is stored securely in your OS keyring.")
        self.lbl_api_status.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        layout.addWidget(self.lbl_api_status)

        layout.addStretch()
        return widget

    def _build_audio_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        devices = list_devices()

        # Mic Device
        self.combo_mic = QComboBox()
        self.combo_mic.addItem("System Default", None)
        for i, dev in enumerate(devices):
            if not dev["is_loopback"]:
                self.combo_mic.addItem(dev["name"], dev["id"])
                if dev["id"] == self._settings.mic_device_id:
                    self.combo_mic.setCurrentIndex(self.combo_mic.count() - 1)

        layout.addRow("Microphone:", self.combo_mic)

        # Loopback Device
        self.combo_lb = QComboBox()
        self.combo_lb.addItem("None", None)
        for i, dev in enumerate(devices):
            if dev["is_loopback"]:
                self.combo_lb.addItem(dev["name"], dev["id"])
                if dev["id"] == self._settings.loopback_device_id:
                    self.combo_lb.setCurrentIndex(self.combo_lb.count() - 1)

        layout.addRow("System Audio (Loopback):", self.combo_lb)
        
        hint = QLabel("On Windows, look for 'WASAPI' devices. On macOS, use 'BlackHole'.")
        hint.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        layout.addRow("", hint)

        return widget

    def _build_prefs_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Word Trigger
        self.spin_trigger = QSpinBox()
        self.spin_trigger.setRange(20, 500)
        self.spin_trigger.setValue(self._settings.word_trigger)
        layout.addRow("Trigger LLM every (words):", self.spin_trigger)

        # Context Window
        self.spin_window = QSpinBox()
        self.spin_window.setRange(1, 20)
        self.spin_window.setSuffix(" min")
        self.spin_window.setValue(self._settings.context_window_minutes)
        layout.addRow("Context Window:", self.spin_window)

        # Opacity
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(20, 100)
        self.slider_opacity.setValue(int(self._settings.overlay_opacity * 100))
        layout.addRow("Overlay Opacity:", self.slider_opacity)

        # Meeting Context
        self.edit_context = QLineEdit()
        self.edit_context.setPlaceholderText("e.g. Budget review / Interview / Project sync")
        self.edit_context.setText(self._settings.meeting_context)
        layout.addRow("Global Context:", self.edit_context)

        return widget

    # --- Actions ---

    def accept(self) -> None:
        """Save all settings and API key before closing."""
        new_api_key = self.edit_api_key.text().strip()
        if new_api_key:
            self._config_store.set_api_key(new_api_key)

        new_settings = replace(
            self._settings,
            mic_device_id=self.combo_mic.currentData(),
            loopback_device_id=self.combo_lb.currentData(),
            word_trigger=self.spin_trigger.value(),
            context_window_minutes=self.spin_window.value(),
            overlay_opacity=self.slider_opacity.value() / 100.0,
            meeting_context=self.edit_context.text().strip(),
        )

        # Emit changes via EventBus
        bus = get_bus()
        for field_name in ["mic_device_id", "loopback_device_id", "word_trigger", "context_window_minutes", "overlay_opacity", "meeting_context"]:
            old_val = getattr(self._settings, field_name)
            new_val = getattr(new_settings, field_name)
            if old_val != new_val:
                bus.emit(SettingsChanged(key=field_name, value=new_val))

        # Save to disk
        self._config_store.save(new_settings)
        super().accept()
