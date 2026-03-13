"""FloatingOverlay window — the main visible surface.

Frameless, semi-transparent, and stays on top of all other windows.
Contains a header bar, a status indicator, and question cards.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QPoint, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from meeting_copilot.application.event_bus import get_bus
from meeting_copilot.domain.events import (
    ApiRateLimited,
    ListeningStateChanged,
    QuestionsReady,
    SettingsChanged,
)
from meeting_copilot.domain.settings import Settings
from meeting_copilot.ui.widgets.question_card import QuestionCard
from meeting_copilot.ui.widgets.status_dot import StatusDot

logger = logging.getLogger(__name__)


class FloatingOverlay(QWidget):
    """The central floating overlay window."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._drag_pos = QPoint()

        # Window Config
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(settings.overlay_opacity)
        self.setFixedWidth(340)

        # UI Components
        self.init_ui()

        # Position
        if settings.overlay_x != -1 and settings.overlay_y != -1:
            self.move(settings.overlay_x, settings.overlay_y)
        else:
            self.center_bottom_right()

        # Subscriptions
        bus = get_bus()
        bus.subscribe_qt(QuestionsReady, self._on_questions)
        bus.subscribe_qt(ListeningStateChanged, self._on_state_changed)
        bus.subscribe_qt(ApiRateLimited, self._on_rate_limit)

    def init_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Inner container for styling (rounded rect)
        self.container = QFrame()
        self.container.setObjectName("OverlayContainer")
        self.container.setStyleSheet("""
            #OverlayContainer {
                background-color: #111827;
                border: 1px solid #1F2937;
                border-radius: 12px;
            }
        """)
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(0)
        self.main_layout.addWidget(self.container)

        # --- Header Bar ---
        self.header = QFrame()
        self.header.setFixedHeight(40)
        self.header.setStyleSheet("border-bottom: 1px solid #1F2937;")
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(12, 0, 8, 0)

        # Icon + Title
        self.lbl_title = QLabel("  Meeting Co-Pilot")
        self.lbl_title.setStyleSheet("color: #14B8A6; font-weight: bold;")
        # Placeholder for actual icon
        self.header_layout.addWidget(self.lbl_title)
        self.header_layout.addStretch()

        # Status Dot
        self.status_dot = StatusDot()
        self.header_layout.addWidget(self.status_dot)

        # Minimize/Hide button
        self.btn_hide = QPushButton("−")
        self.btn_hide.setFixedSize(24, 24)
        self.btn_hide.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #9CA3AF;
                font-size: 18px;
            }
            QPushButton:hover {
                color: #F9FAFB;
            }
        """)
        self.header_layout.addWidget(self.btn_hide)
        self.container_layout.addWidget(self.header)

        # --- Content Area (Questions) ---
        self.cards_area = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_area)
        self.cards_layout.setContentsMargins(12, 12, 12, 12)
        self.cards_layout.setSpacing(10)
        self.container_layout.addWidget(self.cards_area)

        # Empty State
        self.lbl_empty = QLabel("Listening to conversation...")
        self.lbl_empty.setObjectName("EmptyState")
        self.lbl_empty.setStyleSheet("""
            #EmptyState {
                color: #6B7280;
                font-style: italic;
                padding: 10px;
            }
        """)
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cards_layout.addWidget(self.lbl_empty)

        # Card instances
        self._cards: list[QuestionCard] = []

    def center_bottom_right(self) -> None:
        """Position overlay in the bottom-right corner of the primary screen."""
        from PySide6.QtGui import QGuiApplication  # noqa: PLC0415
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = screen.width() - self.width() - 20
        y = screen.height() - self.height() - 20
        self.move(x, y)

    # --- Event Handlers ---

    @Slot(QuestionsReady)
    def _on_questions(self, event: QuestionsReady) -> None:
        """Clear old cards and add new ones."""
        # Clear existing cards
        self._clear_cards()

        self.lbl_empty.hide()

        for q_text in event.questions:
            card = QuestionCard(q_text)
            card.dismissed.connect(lambda c=card: self._remove_card(c)) # type: ignore[misc]
            self.cards_layout.addWidget(card)
            self._cards.append(card)

        # Enforce max 3 cards (oldest first if we ever append)
        while len(self._cards) > 3:
            self._remove_card(self._cards[0])

    @Slot(ListeningStateChanged)
    def _on_state_changed(self, event: ListeningStateChanged) -> None:
        state = "listening" if event.is_listening else "paused"
        self.status_dot.set_state(state)

    @Slot(ApiRateLimited)
    def _on_rate_limit(self, event: ApiRateLimited) -> None:
        self.status_dot.set_state("rate_limited")
        self.setToolTip(f"Rate limited by {event.service}. Retrying in {event.retry_after_seconds}s...")

    def _remove_card(self, card: QuestionCard) -> None:
        self.cards_layout.removeWidget(card)
        card.deleteLater()
        if card in self._cards:
            self._cards.remove(card)

        if not self._cards:
            self.lbl_empty.show()

    def _clear_cards(self) -> None:
        for card in self._cards:
            self.cards_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

    # --- Drag and Drop ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # Save new position to settings
            pos = self.pos()
            get_bus().emit(SettingsChanged(key="overlay_x", value=pos.x()))
            get_bus().emit(SettingsChanged(key="overlay_y", value=pos.y()))
            logger.debug("Overlay moved to %d, %d", pos.x(), pos.y())
            event.accept()
