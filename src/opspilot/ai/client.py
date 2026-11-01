"""The one place that calls Claude.

ClaudeWriter asks for structured output, runs a feature's checks on the draft,
and retries once with the problems listed. If the second draft fails too, it
raises rather than return text that has not passed, so a feature can never
show an unverified draft by accident.
"""

import logging
import os
from collections.abc import Callable

import anthropic
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
MAX_TOKENS = 16000
# Short, tightly specified writing.
EFFORT = "low"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIUnavailable(Exception):
    """No verified text could be produced. The message is safe to show."""


def build_client() -> anthropic.Anthropic | None:
    """A client, or None when no key is set: the rest of the API works without one."""
    return anthropic.Anthropic() if os.environ.get("ANTHROPIC_API_KEY") else None


class ClaudeWriter:
    def __init__(self, client: anthropic.Anthropic, model: str):
        self.client = client
        self.model = model

    def write(self, system: str, message: str, output_format: type[BaseModel],
              problems_in: Callable[[BaseModel], list[str]]) -> dict:
        """A draft that passed `problems_in`, with the model, attempts and token usage."""
        problems = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = self._request(system, self._with_feedback(message, problems), output_format)
            usage["input_tokens"] += response.usage.input_tokens
            usage["output_tokens"] += response.usage.output_tokens
            draft = self._read_draft(response)
            problems = problems_in(draft)
            if not problems:
                logger.info("%s attempts=%d usage=%s", output_format.__name__, attempt, usage)
                return {"draft": draft, "model": response.model, "attempts": attempt, "usage": usage}
            logger.warning("%s draft rejected: %s", output_format.__name__, problems)
        raise AIUnavailable("The text did not pass the number check, so it was not shown.")

    def _request(self, system: str, message: str, output_format: type[BaseModel]):
        kwargs = {}
        if "haiku" not in self.model:  # Haiku has no server-side fallback
            kwargs = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        try:
            return self.client.beta.messages.parse(
                model=self.model, max_tokens=MAX_TOKENS, system=system,
                messages=[{"role": "user", "content": message}],
                output_format=output_format, output_config={"effort": EFFORT}, **kwargs,
            )
        except anthropic.AuthenticationError as error:
            raise AIUnavailable("The AI service rejected the API key.") from error
        except anthropic.RateLimitError as error:
            raise AIUnavailable("The AI service is busy. Try again shortly.") from error
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as error:
            logger.warning("Claude request failed: %s", error)
            raise AIUnavailable("The AI service could not be reached.") from error

    @staticmethod
    def _with_feedback(message: str, problems: list[str]) -> str:
        if not problems:
            return message
        return message + "\n\nAn earlier draft was rejected. Avoid these problems:\n- " + "\n- ".join(problems)

    @staticmethod
    def _read_draft(response):
        if response.stop_reason != "end_turn" or response.parsed_output is None:
            logger.warning("Claude stopped early: %s", response.stop_reason)
            raise AIUnavailable("The AI service did not return a complete answer.")
        return response.parsed_output
