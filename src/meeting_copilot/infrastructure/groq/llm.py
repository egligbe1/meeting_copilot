"""GroqLLMClient — concise interview-answer coaching via Groq."""

from __future__ import annotations

import json
import logging

from groq import Groq, RateLimitError
from groq.types.chat.completion_create_params import (
    ResponseFormatResponseFormatJsonSchema,
)

from meeting_copilot.application.event_bus import get_bus
from meeting_copilot.domain.events import (
    AnswerReady,
    ApiRateLimited,
    ErrorOccurred,
)
from meeting_copilot.domain.settings import Settings

logger = logging.getLogger(__name__)

INTERVIEW_COACH_SYSTEM_PROMPT = """\
You are a concise interview coach. Use the most recent interviewer question in
the transcript and help the candidate formulate an honest, natural response.
The focus is data engineering, data architecture, or behavioral interviews.

Rules:
- The transcript may contain both interviewer and candidate speech. Use it to
  identify the latest interviewer question, but do not treat transcript claims
  as verified candidate background.
- Never invent or imply the candidate has experience, metrics, employers,
  credentials, projects, or outcomes that are not in the supplied candidate
  context. Do not turn interviewer examples into candidate experience.
- If candidate context does not support a personal claim, give a brief,
  speakable template with explicit placeholders, or say more personal context
  is needed. Never fill those placeholders with invented specifics.
- For technical questions, lead with the decision or design, then mention
  trade-offs, reliability, cost, security, and observability only when relevant.
- For behavioral questions, suggest a compact STAR-shaped answer based only on
  supplied candidate context. Do not make up a story.
- Keep the spoken answer under 90 words and make it easy to say aloud.
"""

ANSWER_SCHEMA: ResponseFormatResponseFormatJsonSchema = {
    "type": "json_schema",
    "json_schema": {
        "name": "interview_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "talking_points": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "follow_up": {"type": ["string", "null"]},
            },
            "required": ["answer", "talking_points", "follow_up"],
            "additionalProperties": False,
        },
    },
}


class GroqLLMClient:
    """Send transcript context to Groq GPT-OSS and emit answer events."""

    def __init__(self, settings: Settings, api_key: str) -> None:
        self._settings = settings
        self._client = Groq(api_key=api_key, timeout=20.0, max_retries=0)

    def generate_answer(
        self,
        transcript_context: str,
        word_count: int = 0,
        context_generation: int = 0,
    ) -> None:
        """Generate answer guidance from *transcript_context* and emit AnswerReady.

        Parameters
        ----------
        transcript_context:
            Formatted transcript string from the rolling buffer.
        word_count:
            Number of context words (for reporting in the event).
        """
        bus = get_bus()

        user_content = f"Interview transcript (newest speech is most important):\n\n{transcript_context}"
        if self._settings.meeting_context:
            user_content = f"Candidate / interview context: {self._settings.meeting_context}\n\n" + user_content
        user_content = f"Interview focus: {self._settings.interview_focus}\n\n" + user_content

        try:
            response = self._client.chat.completions.create(
                model=self._settings.groq_model_llm,
                messages=[
                    {"role": "system", "content": INTERVIEW_COACH_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ],
                max_completion_tokens=1200,
                reasoning_effort="low",
                response_format=ANSWER_SCHEMA,
            )

            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise ValueError(
                    "Groq returned an empty answer; try again or check model limits."
                )

            # Parse JSON array of strings
            try:
                payload = json.loads(content)
                if not isinstance(payload, dict) or not isinstance(payload.get("answer"), str):
                    raise ValueError("Response is not an answer object")
                points = payload.get("talking_points", [])
                if not isinstance(points, list):
                    raise ValueError("talking_points is not a list")
                answer = payload["answer"].strip()
                if not answer:
                    raise ValueError("Response contains an empty answer")
                talking_points = tuple(str(point).strip() for point in points[:3] if str(point).strip())
                follow_up_raw = payload.get("follow_up")
                follow_up = str(follow_up_raw).strip() if follow_up_raw else None
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
                AnswerReady(
                    answer=answer,
                    talking_points=talking_points,
                    follow_up=follow_up,
                    context_word_count=word_count,
                    context_generation=context_generation,
                )
            )
            logger.info(
                "Generated interview answer guidance from %d context words",
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
