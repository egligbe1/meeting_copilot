"""SystemTrayManager — manages the taskbar icon and its context menu.

Allows starting/stopping the orchestrator, toggling overlay visibility,
opening settings, and viewing sessions.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from meeting_copilot.application.event_bus import get_bus
from meeting_copilot.domain.events import ListeningStateChanged
from meeting_copilot.infrastructure.persistence.config import ConfigStore
from meeting_copilot.infrastructure.persistence.session import SessionLogger

logger = logging.getLogger(__name__)


class SystemTrayManager(QObject):
    """Manages the system tray icon and its context menu."""

    def __init__(self, overlay: QWidget, orchestrator: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._overlay = overlay
        self._orchestrator = orchestrator

        # Create tray icon
        self.tray_icon = QSystemTrayIcon(self._generate_icon(), parent)
        self.tray_icon.setToolTip("Interview Co-Pilot")

        # Create menu
        self.menu = QMenu()
        self.menu.setStyleSheet("QMenu { background-color: #111827; color: white; border: 1px solid #1F2937; }")

        # Actions
        self.act_toggle = QAction("● Listening", self)
        self.act_toggle.setCheckable(True)
        self.act_toggle.setChecked(False)
        self.act_toggle.triggered.connect(self._toggle_listening)

        self.act_show = QAction("Show Overlay", self)
        self.act_show.triggered.connect(self._toggle_overlay)

        self.act_settings = QAction("Settings", self)
        self.act_settings.triggered.connect(self._open_settings)

        self.act_sessions = QAction("View Sessions Folder", self)
        self.act_sessions.triggered.connect(self._open_sessions)

        self.act_quit = QAction("Quit", self)
        self.act_quit.triggered.connect(QApplication.instance().quit) # type: ignore[union-attr]

        # Add to menu
        self.menu.addAction(self.act_toggle)
        self.menu.addSeparator()
        self.menu.addAction(self.act_show)
        self.menu.addAction(self.act_sessions)
        self.menu.addAction(self.act_settings)
        self.menu.addSeparator()
        self.menu.addAction(self.act_quit)

        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.menu.aboutToShow.connect(self._sync_overlay_action)

        # Subscriptions
        get_bus().subscribe_qt(ListeningStateChanged, self._update_menu)

    def show(self) -> None:
        self.tray_icon.show()

    def hide(self) -> None:
        self.tray_icon.hide()

    # --- Icons ---

    def _generate_icon(self) -> QIcon:
        """Generate a procedural teal circle icon."""
        from PySide6.QtGui import QBrush, QPixmap  # noqa: PLC0415
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#0D9488"))) # Teal
        painter.drawEllipse(4, 4, 24, 24)
        painter.end()

        return QIcon(pixmap)

    # --- SLOTS ---

    @Slot()
    def _toggle_listening(self) -> None:
        if self.act_toggle.isChecked():
            self._orchestrator.start()
        else:
            self._orchestrator.stop()

    @Slot()
    def _toggle_overlay(self) -> None:
        visible = not self._overlay.isVisible()
        self._overlay.setVisible(visible)
        self.act_show.setText("Hide Overlay" if visible else "Show Overlay")

    @Slot()
    def _sync_overlay_action(self) -> None:
        self.act_show.setText(
            "Hide Overlay" if self._overlay.isVisible() else "Show Overlay"
        )

    @Slot()
    def _open_settings(self) -> None:
        from meeting_copilot.ui.settings_dialog import SettingsDialog
        config_store = ConfigStore()
        settings = config_store.load()
        dialog = SettingsDialog(settings)
        if dialog.exec():
            logger.info("Settings updated via dialog")

    @Slot()
    def _open_sessions(self) -> None:
        path = SessionLogger.sessions_root()
        QDesktopServices.openUrl(f"file:///{path}")

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_overlay()

    @Slot(ListeningStateChanged)
    def _update_menu(self, event: ListeningStateChanged) -> None:
        self.act_toggle.setChecked(event.is_listening)
        self.act_toggle.setText("● Listening" if event.is_listening else "○ Paused")

    def _on_error(self, event: Any) -> None:
        """Show a tray notification for errors."""
        self.tray_icon.showMessage(
            f"Error: {event.source}",
            event.message,
            QSystemTrayIcon.MessageIcon.Warning if event.recoverable else QSystemTrayIcon.MessageIcon.Critical
        )
