"""QuestionCard widget — displays a single AI-generated question.

Styled with a dark background, a teal left border accent, and a dismiss button.
Includes a fade-in animation on show.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Signal, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QGraphicsOpacityEffect


class QuestionCard(QFrame):
    """A dismissible question card for the overlay."""

    dismissed = Signal()  # Emitted when the user clicks 'X'

    def __init__(self, question: str, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("QuestionCard")

        # Layout
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.layout.setSpacing(8)

        # Teal side accent
        self.setStyleSheet("""
            #QuestionCard {
                background-color: #1F2937;
                border-radius: 8px;
                border-left: 3px solid #0D7377;
            }
        """)

        # Question text
        self.label = QLabel(question)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color: #F9FAFB; font-weight: 500;")
        self.layout.addWidget(self.label)

        # Dismiss button
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #9CA3AF;
                font-weight: bold;
                border-radius: 4px;
                padding: 0;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #374151;
                color: #F9FAFB;
            }
        """)
        self.btn_close.clicked.connect(self.dismissed.emit)
        self.layout.addWidget(self.btn_close, alignment=Qt.AlignmentFlag.AlignTop)

        # Fade-in animation
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.fade_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_anim.setDuration(400)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self.fade_anim.start()
