"""Tests for floating overlay controls."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from meeting_copilot.domain.events import (
    AnswerReady,
    ClearContextRequested,
)
from meeting_copilot.domain.settings import Settings
from meeting_copilot.ui.overlay import FloatingOverlay


def test_close_button_hides_overlay_and_keeps_app_running(qtbot: QtBot) -> None:
    overlay = FloatingOverlay(Settings())
    qtbot.addWidget(overlay)
    overlay.show()
    assert overlay.isVisible()

    qtbot.mouseClick(  # type: ignore[no-untyped-call]
        overlay.btn_close, Qt.MouseButton.LeftButton
    )

    assert not overlay.isVisible()
    assert overlay.btn_close.toolTip() == "Close overlay"


def test_clear_button_removes_answer_and_requests_new_context(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = Mock()
    bus.subscribe_qt = Mock()
    monkeypatch.setattr("meeting_copilot.ui.overlay.get_bus", lambda: bus)
    overlay = FloatingOverlay(Settings())
    qtbot.addWidget(overlay)
    overlay.show()
    overlay._on_answer(
        AnswerReady(
            answer="Old answer",
            talking_points=("Old context",),
            follow_up=None,
            context_word_count=12,
        )
    )
    assert overlay._cards

    qtbot.mouseClick(  # type: ignore[no-untyped-call]
        overlay.btn_clear, Qt.MouseButton.LeftButton
    )

    assert not overlay._cards
    assert overlay.lbl_empty.isVisible()
    assert "next question" in overlay.lbl_empty.text()
    overlay._on_answer(
        AnswerReady(
            answer="Late old answer",
            talking_points=(),
            follow_up=None,
            context_word_count=12,
            context_generation=0,
        )
    )
    assert not overlay._cards
    event = bus.emit.call_args.args[0]
    assert isinstance(event, ClearContextRequested)
