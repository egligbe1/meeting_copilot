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
You are an expert executive meeting coach.
Analyze the provided transcript to identify:
1. Core tensions or unstated assumptions.
2. Missing logical links or vague next steps.
3. Strategic risks or opportunities for deeper exploration.

Based on this analysis, suggest sharp, focused questions for the participant labeled 'You' to ask. 

Rules:
- Questions must be open-ended and drive clarity or strategic alignment.
- Keep each question under 20 words.
- Return EXACTLY 2-3 questions.
- Output ONLY a valid JSON array of strings. No thinking block, no preamble.
- Example: ["What is the specific bottleneck in the current design?", "How does this change impact the Q4 delivery goal?"]
"""


SUMMARIZER_SYSTEM_PROMPT = """\
You are an expert meeting recorder and analyst.
Analyze the provided transcript to generate a structured meeting summary.

Structure the output in Markdown:
1. **Executive Summary**: A high-level 3-sentence overview.
2. **Key Decisions**: Bullet points of what was agreed upon.
3. **Action Items**: Prioritized list with owners (if identifiable).
4. **Context & Themes**: Brief notes on the general tone or recurring topics.

Rules:
- Be concise and objective.
- If no specific decisions were made, state "No formal decisions were recorded."
- Use standard Markdown formatting.
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

        try:
            response = self._client.chat.completions.create(
                model=self._settings.groq_model_llm,
                messages=[
                    {"role": "system", "content": ADVISOR_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Transcript:\n\n{transcript_context}",
                    },
                ],
                max_tokens=300,
                temperature=0.4,
            )

            content = (response.choices[0].message.content or "").strip()

            # Parse JSON array of strings
            try:
                # Robust extraction: find the first '[' and last ']' to ignore preamble/thinking
                start_idx = content.find("[")
                end_idx = content.rfind("]")
                if start_idx == -1 or end_idx == -1:
                    raise ValueError("No JSON array found in response")
                
                json_str = content[start_idx : end_idx + 1]
                questions = json.loads(json_str)

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

    def generate_summary(self, transcript_full: str) -> None:
        """Generate a final meeting summary from the full transcript."""
        from meeting_copilot.domain.events import SessionSummaryReady  # noqa: PLC0415
        bus = get_bus()

        try:
            response = self._client.chat.completions.create(
                model=self._settings.groq_model_llm,
                messages=[
                    {"role": "system", "content": SUMMARIZER_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Full Transcript:\n\n{transcript_full}",
                    },
                ],
                temperature=0.3,
            )

            summary_md = (response.choices[0].message.content or "").strip()
            bus.emit(SessionSummaryReady(summary_md=summary_md))
            logger.info("Generated final meeting summary")

        except Exception as exc:
            bus.emit(
                ErrorOccurred(
                    source="groq_summarizer",
                    message=str(exc),
                    recoverable=True,
                )
            )
            logger.exception("LLM summary generation error")
