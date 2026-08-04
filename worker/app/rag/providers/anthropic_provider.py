"""Anthropic Claude implementation of app.rag.llm.RootCauseLLM.

Haiku 4.5, not a bigger model — per docs/IMPLEMENTATION_PLAN.md Section 7,
this is a short, structured, retrieval-grounded task, not one that needs
frontier-model reasoning. This was the original (and, funding permitting,
default-again) provider; see app/rag/providers/gemini_provider.py for the
second implementation behind the same interface and app/rag/llm.py's
get_llm_provider() for how LLM_PROVIDER selects between them.

tool_choice is forced to the single tool defined in app/rag/prompts.py's
schema — see that module's docstring for why forcing a single tool is a
security property, not just a convenience.
"""

import os

from anthropic import AsyncAnthropic
from anthropic.types import ToolParam

from app.rag.llm import RootCauseAnalysis
from app.rag.prompts import (
    ROOT_CAUSE_TOOL_DESCRIPTION,
    ROOT_CAUSE_TOOL_NAME,
    ROOT_CAUSE_TOOL_SCHEMA,
)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

_TOOL: ToolParam = {
    "name": ROOT_CAUSE_TOOL_NAME,
    "description": ROOT_CAUSE_TOOL_DESCRIPTION,
    "input_schema": ROOT_CAUSE_TOOL_SCHEMA,
}


class AnthropicRootCauseLLM:
    def __init__(self) -> None:
        self._client: AsyncAnthropic | None = None

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            self._client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        return self._client

    async def generate(self, system_prompt: str, user_message: str) -> RootCauseAnalysis:
        response = await self._get_client().messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": ROOT_CAUSE_TOOL_NAME},
            messages=[{"role": "user", "content": user_message}],
        )

        tool_use_block = next(block for block in response.content if block.type == "tool_use")
        return RootCauseAnalysis.model_validate(tool_use_block.input)
