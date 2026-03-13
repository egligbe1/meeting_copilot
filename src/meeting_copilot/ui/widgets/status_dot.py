"""StatusDot widget — indicates listening state with a pulsing circle.

States:
    * 'listening' — teal, pulsing opacity (0.4 <-> 1.0)
    * 'paused'    — red, solid circle
    * 'rate_limited' — orange, solid circle
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Property, QPropertyAnimation, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

COLOR_LISTENING = "#14B8A6"  # Teal-500
COLOR_PAUSED = "#EF4444"     # Red-500
COLOR_RATE_LIMIT = "#F59E0B" # Amber-500


class StatusDot(QWidget):
    """Circular status indicator with pulsing animation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._color = QColor(COLOR_PAUSED)
        self._pulse_opacity = 1.0
        self._state = "paused"

        # Pulse animation for 'listening' state
        self._pulse_anim = QPropertyAnimation(self, b"pulse_opacity")
        self._pulse_anim.setDuration(1500)
        self._pulse_anim.setStartValue(0.4)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setLoopCount(-1)  # Forever
        self._pulse_anim.setKeyValueAt(0.5, 1.0)
        self._pulse_anim.setEndValue(0.4)

    # --- Properties ---

    @Property(float)
    def pulse_opacity(self) -> float:
        return self._pulse_opacity

    @pulse_opacity.setter
    def pulse_opacity(self, value: float) -> None:
        self._pulse_opacity = value
        self.update()

    # --- State Management ---

    def set_state(self, state: str) -> None:
        """Set the indicator state: 'listening', 'paused', or 'rate_limited'."""
        if state == self._state:
            return

        self._state = state
        self._pulse_anim.stop()
        self._pulse_opacity = 1.0

        if state == "listening":
            self._color = QColor(COLOR_LISTENING)
            self._pulse_anim.start()
        elif state == "rate_limited":
            self._color = QColor(COLOR_RATE_LIMIT)
        else: # paused
            self._color = QColor(COLOR_PAUSED)

        self.update()

    # --- Painting ---

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = QColor(self._color)
        color.setAlphaF(self._pulse_opacity)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))

        # Draw circle centered in widget
        painter.drawEllipse(1, 1, 10, 10)
