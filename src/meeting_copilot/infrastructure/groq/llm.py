"""GroqLLMClient — question generation via Groq Llama 4 API.

Sends transcript context to the LLM and returns suggested questions.
The system prompt is defined as a module-level constant.
"""

from __future__ import annotations

import json
import logging

from groq import Groq, RateLimitError

from meeting_copilot.application.event_bus import get_bus
from meeting_copilot.domain.events import (
    ApiRateLimited,
    ErrorOccurred,
    QuestionsReady,
)
from meeting_copilot.domain.settings import Settings

logger = logging.getLogger(__name__)

ADVISOR_SYSTEM_PROMPT = """\
You are a strategic meeting advisor.
You will receive a meeting transcript and optional metadata.
Your goal is to suggest 2-3 high-impact, strategic questions that help the participant 'You' 
synthesize the discussion, identify hidden risks, or drive the conversation toward its primary goal.

Analysis Process:
1. Synthesize the high-level meeting goal from the context and historical transcript.
2. Identify "missing perspectives" — what is NOT being said that should be?
3. Pinpoint unspoken assumptions or logical gaps in the current dialogue.
4. Focus on the MOST RECENT dialogue to identify immediate points of leverage.

Rules:
- Questions must be deep, strategic, and open-ended.
- Avoid obvious clarification; aim for synthesis and insight.
- Keep each question under 20 words.
- Return ONLY a raw JSON array of strings. No markdown, no preamble.
"""


class GroqLLMClient:
    """Send transcript context to Groq Llama 4 and emit question events."""

    def __init__(self, settings: Settings, api_key: str) -> None:
        self._settings = settings
        self._client = Groq(api_key=api_key)

    def generate_questions(
        self, transcript_context: str, word_count: int = 0
    ) -> None:
        """Generate questions from *transcript_context* and emit QuestionsReady.

        Parameters
        ----------
        transcript_context:
            Formatted transcript string from the rolling buffer.
        word_count:
            Number of context words (for reporting in the event).
        """
        bus = get_bus()

        # Build user message with optional meeting context
        user_content = f"Transcript:\n\n{transcript_context}"
        if self._settings.meeting_context:
            user_content = f"Meeting Context: {self._settings.meeting_context}\n\n" + user_content

        try:
            response = self._client.chat.completions.create(
                model=self._settings.groq_model_llm,
                messages=[
                    {"role": "system", "content": ADVISOR_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ],
                max_tokens=400,
                temperature=0.5,
            )

            content = (response.choices[0].message.content or "").strip()

            # Parse JSON array of strings
            try:
                questions = json.loads(content)
                if not isinstance(questions, list):
                    raise ValueError("Response is not a JSON array")
                questions = tuple(str(q) for q in questions)
            except (json.JSONDecodeError, ValueError) as parse_err:
                logger.warning(
                    "LLM returned malformed JSON: %s — raw: %s",
                    parse_err,
                    content[:200],
                )
                bus.emit(
                    ErrorOccurred(
                        source="groq_llm",
                        message=f"Malformed JSON response: {parse_err}",
                        recoverable=True,
                    )
                )
                return

            bus.emit(
                QuestionsReady(
                    questions=questions,
                    context_word_count=word_count,
                )
            )
            logger.info(
                "Generated %d questions from %d context words",
                len(questions),
                word_count,
            )

        except RateLimitError as exc:
            retry_after = int(
                getattr(exc.response, "headers", {}).get("retry-after", 30)
            )
            bus.emit(
                ApiRateLimited(
                    service="groq_llm", retry_after_seconds=retry_after
                )
            )
            logger.warning("LLM rate limited — retry after %ds", retry_after)

        except Exception as exc:
            bus.emit(
                ErrorOccurred(
                    source="groq_llm",
                    message=str(exc),
                    recoverable=True,
                )
            )
            logger.exception("LLM question generation error")
