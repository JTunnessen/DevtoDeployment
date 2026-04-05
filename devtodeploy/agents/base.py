from __future__ import annotations

from abc import ABC, abstractmethod

import anthropic

from devtodeploy.config import Config
from devtodeploy.state import PipelineState
from devtodeploy.utils.logging import get_logger
from devtodeploy.utils.retry import with_retry


class PipelineHaltException(Exception):
    """Raised by an agent to stop the entire pipeline."""


class BaseAgent(ABC):
    name: str = "BaseAgent"
    stage_number: int = 0

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.logger = get_logger(self.name)

    @abstractmethod
    def run(self, state: PipelineState) -> PipelineState:
        ...

    @with_retry(max_attempts=3, min_wait=2, max_wait=8)
    def _call_claude(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 8096,
    ) -> str:
        """Call the Claude API and return the text content of the first response block."""
        response = self.client.messages.create(
            model=self.config.claude_model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.content[0].text  # type: ignore[union-attr]
