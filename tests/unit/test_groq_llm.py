"""Tests for Groq answer generation and structured response handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from meeting_copilot.domain.events import AnswerReady, ErrorOccurred
from meeting_copilot.domain.settings import Settings
from meeting_copilot.infrastructure.groq.llm import (
    ANSWER_SCHEMA,
    GroqLLMClient,
)


def _response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


def test_generate_answer_uses_structured_low_effort_completion(
    monkeypatch,
) -> None:
    bus = Mock()
    monkeypatch.setattr("meeting_copilot.infrastructure.groq.llm.get_bus", lambda: bus)
    create = Mock(
        return_value=_response(
            '{"answer":"Use a truthful example.","talking_points":["Outcome"],'
            '"follow_up":null}'
        )
    )
    client = object.__new__(GroqLLMClient)
    client._settings = Settings(meeting_context="Built ETL pipelines.")
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    client.generate_answer(
        "[10:00] Meeting: Tell me about your work.",
        8,
        context_generation=4,
    )

    kwargs = create.call_args.kwargs
    assert kwargs["response_format"] == ANSWER_SCHEMA
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["max_completion_tokens"] == 1200
    assert "Built ETL pipelines." in kwargs["messages"][1]["content"]
    event = bus.emit.call_args.args[0]
    assert isinstance(event, AnswerReady)
    assert event.answer == "Use a truthful example."
    assert event.context_generation == 4


def test_generate_answer_reports_empty_model_response(monkeypatch) -> None:
    bus = Mock()
    monkeypatch.setattr("meeting_copilot.infrastructure.groq.llm.get_bus", lambda: bus)
    client = object.__new__(GroqLLMClient)
    client._settings = Settings()
    client._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=Mock(return_value=_response("")))
        )
    )

    client.generate_answer("[10:00] Meeting: Tell me about your work.", 8)

    event = bus.emit.call_args.args[0]
    assert isinstance(event, ErrorOccurred)
    assert "empty answer" in event.message


def test_empty_candidate_answer_is_not_emitted(monkeypatch) -> None:
    bus = Mock()
    monkeypatch.setattr("meeting_copilot.infrastructure.groq.llm.get_bus", lambda: bus)
    client = object.__new__(GroqLLMClient)
    client._settings = Settings()
    client._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=Mock(
                    return_value=_response(
                        '{"answer":"","talking_points":[],"follow_up":null}'
                    )
                )
            )
        )
    )

    client.generate_answer("[10:00] Meeting: Tell me about your work.", 8)

    event = bus.emit.call_args.args[0]
    assert isinstance(event, ErrorOccurred)
    assert "empty answer" in event.message
