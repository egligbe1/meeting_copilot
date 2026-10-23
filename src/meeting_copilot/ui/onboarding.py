"""OnboardingWizard — first-run experience for users.

Guided setup pages:
    1. Welcome — App overview.
    2. API Key — Mandatory Groq API key entry and validation.
    3. Audio Setup — Device selection for mic and system audio.
    4. Preferences — Initial LLM triggers and context window.
    5. Ready — Summary and final confirmation.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from meeting_copilot.domain.settings import Settings
from meeting_copilot.infrastructure.audio.devices import list_devices
from meeting_copilot.infrastructure.persistence.config import ConfigStore

logger = logging.getLogger(__name__)


class OnboardingWizard(QWizard):
    """Guided multi-page setup for first-time users."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Interview Co-Pilot Setup")
        self.setFixedSize(550, 450)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        
        self._settings = settings
        self._config_store = ConfigStore()

        # Pages
        self.addPage(WelcomePage())
        self.addPage(ApiKeyPage(self._config_store))
        self.addPage(AudioSetupPage(settings))
        self.addPage(ReadyPage())

        self.setButtonText(QWizard.WizardButton.FinishButton, "Start Listening")

    def accept(self) -> None:
        """Finalize settings and save configuration."""
        # Retrieve values from pages (via field system)
        api_key = self.field("api_key").strip()
        mic_id = self.field("mic_id")
        lb_id = self.field("lb_id")

        self._config_store.set_api_key(api_key)
        
        new_settings = replace(
            self._settings,
            mic_device_id=mic_id if mic_id != -1 else None,
            loopback_device_id=lb_id, # Preserve -1 for Auto, None for Disabled
        )
        self._config_store.save(new_settings)
        
        super().accept()


class WelcomePage(QWizardPage):
    """Step 1: Introduction."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Welcome to Interview Co-Pilot")
        self.setSubTitle("Real-time, concise answer guidance for interviews.")

        layout = QVBoxLayout(self)
        info = QLabel(
            "This application listens to interview audio and offers "
            "concise answer guidance for data engineering, data architecture, "
            "and behavioral questions.\n\n"
            "We'll need a free Groq API key and your audio device "
            "preferences to get started."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addStretch()


class ApiKeyPage(QWizardPage):
    """Step 2: Groq API Key."""

    def __init__(self, config_store: ConfigStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("API Configuration")
        self.setSubTitle("Enter your free Groq API key to power transcription and AI.")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.edit_key = QLineEdit()
        self.edit_key.setPlaceholderText("gsk_...")
        self.edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.registerField("api_key*", self.edit_key)
        layout.addWidget(self.edit_key)

        help_lbl = QLabel(
            "<a href='https://console.groq.com' style='color: #14B8A6;'>Get a free key at console.groq.com</a>"
        )
        help_lbl.setOpenExternalLinks(True)
        layout.addWidget(help_lbl)
        
        layout.addSpacing(20)
        layout.addWidget(QLabel("No credit card required. Free tier is 100% supported."))
        layout.addStretch()


class AudioSetupPage(QWizardPage):
    """Step 3: Device Picker."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Audio Setup")
        self.setSubTitle("Choose which devices should be monitored.")

        layout = QFormLayout(self)
        layout.setSpacing(15)

        devices = list_devices()

        self.combo_mic = QComboBox()
        self.combo_mic.addItem("System Default", -1)
        for dev in devices:
            if not dev["is_loopback"]:
                self.combo_mic.addItem(dev["name"], dev["id"])

        self.combo_lb = QComboBox()
        self.combo_lb.addItem("Detect Automatically", -1)
        for dev in devices:
            if dev["is_loopback"]:
                self.combo_lb.addItem(dev["name"], dev["id"])

        layout.addRow("Microphone:", self.combo_mic)
        layout.addRow("System Audio:", self.combo_lb)

        self.registerField("mic_id", self.combo_mic, "currentData")
        self.registerField("lb_id", self.combo_lb, "currentData")

        layout.addRow("", QLabel("\nOn macOS, install BlackHole and route your call through a Multi-Output Device in Audio MIDI Setup."))


class ReadyPage(QWizardPage):
    """Final Step."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("You're All Set!")
        self.setSubTitle("Configuration complete.")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Interview Co-Pilot will now run in the background.\n\n"
            "You can find the controls and settings in the system tray "
            "at any time."
        ))
        layout.addStretch()
