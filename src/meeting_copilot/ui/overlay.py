"""FloatingOverlay window — the main visible surface.

Frameless, semi-transparent, and stays on top of all other windows.
Contains a header bar, a status indicator, and question cards.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QPoint, Qt, Slot
from PySide6.QtGui import QMouseEvent, QShowEvent
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
    AnswerReady,
    ApiRateLimited,
    ClearContextRequested,
    ContextCleared,
    ListeningStateChanged,
    SettingsChanged,
)
from meeting_copilot.domain.settings import Settings
from meeting_copilot.ui.widgets.question_card import AnswerCard
from meeting_copilot.ui.widgets.status_dot import StatusDot

logger = logging.getLogger(__name__)


class FloatingOverlay(QWidget):
    """The central floating overlay window."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._drag_pos = QPoint()
        self._context_generation = 0

        # Window Config
        self._apply_floating_window_flags()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if sys.platform == "darwin":
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setWindowOpacity(settings.overlay_opacity)
        self.setFixedWidth(600)
        self.setMinimumHeight(300)
        self.resize(600, 340)

        # UI Components
        self.init_ui()

        # Position
        if settings.overlay_x != -1 and settings.overlay_y != -1:
            self.move(settings.overlay_x, settings.overlay_y)
        else:
            self.center_bottom_right()

        # Subscriptions
        bus = get_bus()
        bus.subscribe_qt(AnswerReady, self._on_answer)
        bus.subscribe_qt(ContextCleared, self._on_context_cleared)
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
        self.lbl_title = QLabel("  Interview Co-Pilot")
        self.lbl_title.setStyleSheet("color: #14B8A6; font-weight: bold;")
        # Placeholder for actual icon
        self.header_layout.addWidget(self.lbl_title)
        self.header_layout.addStretch()

        # Status Dot
        self.status_dot = StatusDot()
        self.header_layout.addWidget(self.status_dot)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setToolTip(
            "Clear the current answer and start fresh for the next question"
        )
        self.btn_clear.setAccessibleName("Clear interview context")
        self.btn_clear.clicked.connect(self._clear_context)
        self.header_layout.addWidget(self.btn_clear)

        # Close button hides the overlay while keeping the app available in the tray.
        self.btn_close = QPushButton("×")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setToolTip("Close overlay")
        self.btn_close.setAccessibleName("Close overlay")
        self.btn_close.setStyleSheet("""
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
        self.btn_close.clicked.connect(self.hide)
        self.header_layout.addWidget(self.btn_close)
        self.container_layout.addWidget(self.header)

        # --- Content Area (Answer guidance) ---
        self.cards_area = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_area)
        self.cards_layout.setContentsMargins(12, 12, 12, 12)
        self.cards_layout.setSpacing(10)
        self.container_layout.addWidget(self.cards_area)

        # Empty State
        self.lbl_empty = QLabel("Listening for the interviewer’s question…")
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
        self._cards: list[AnswerCard] = []

    def _apply_floating_window_flags(self) -> None:
        """Create a frameless tool panel that floats above normal windows."""
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )

    def showEvent(self, event: QShowEvent) -> None:
        """Set the native macOS window level after Qt creates the panel."""
        super().showEvent(event)
        self.raise_()
        if sys.platform == "darwin":
            self._set_macos_window_level()

    def _set_macos_window_level(self) -> None:
        """Keep the overlay visible above apps and in macOS full-screen Spaces."""
        try:
            import objc  # type: ignore[import-untyped]
            from AppKit import (  # type: ignore[import-untyped]
                NSStatusWindowLevel,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
            )

            native_view = objc.objc_object(c_void_p=int(self.winId()))
            native_window = native_view.window()
            native_window.setLevel_(NSStatusWindowLevel)
            native_window.setHidesOnDeactivate_(False)
            native_window.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            native_window.orderFrontRegardless()
        except Exception:
            logger.exception("Failed to keep the overlay above macOS windows")

    def center_bottom_right(self) -> None:
        """Position overlay in the bottom-right corner of the primary screen."""
        from PySide6.QtGui import QGuiApplication  # noqa: PLC0415
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = screen.width() - self.width() - 20
        y = screen.height() - self.height() - 20
        self.move(x, y)

    # --- Event Handlers ---

    @Slot(AnswerReady)
    def _on_answer(self, event: AnswerReady) -> None:
        """Replace old guidance with the answer for the latest question."""
        if event.context_generation != self._context_generation:
            return

        # Clear existing cards
        self._clear_cards()

        self.lbl_empty.hide()

        card = AnswerCard(event.answer, event.talking_points, event.follow_up)
        card.dismissed.connect(lambda c=card: self._remove_card(c))
        self.cards_layout.addWidget(card)
        self._cards.append(card)

    @Slot()
    def _clear_context(self) -> None:
        """Clear visible guidance and ask the pipeline to discard old context."""
        self._context_generation += 1
        self._clear_cards()
        self.lbl_empty.setText("Cleared — listening for the next question…")
        self.lbl_empty.show()
        get_bus().emit(ClearContextRequested())

    @Slot(ContextCleared)
    def _on_context_cleared(self, event: ContextCleared) -> None:
        self._context_generation = event.generation
        self._clear_cards()
        self.lbl_empty.setText("Cleared — listening for the next question…")
        self.lbl_empty.show()

    @Slot(ListeningStateChanged)
    def _on_state_changed(self, event: ListeningStateChanged) -> None:
        state = "listening" if event.is_listening else "paused"
        self.status_dot.set_state(state)

    @Slot(ApiRateLimited)
    def _on_rate_limit(self, event: ApiRateLimited) -> None:
        self.status_dot.set_state("rate_limited")
        self.setToolTip(f"Rate limited by {event.service}. Retrying in {event.retry_after_seconds}s...")

    def _remove_card(self, card: AnswerCard) -> None:
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
