"""Gemini implementation of app.rag.llm.RootCauseLLM — the funded path
as of Phase 6's live verification (see app/rag/providers/anthropic_provider.py
for the original implementation behind the same interface, still fully
wired and selectable via LLM_PROVIDER=anthropic).

gemini-flash-lite-latest: the alias for Google's current flash-lite
model, not a dated/pinned version — a pinned model name (originally
gemini-2.5-flash-lite here) can 404 for new API keys once Google
considers it superseded, discovered live during Phase 6/10 verification.
Free tier (15 RPM / 1,000 requests per day) is comfortably enough for
this project's actual incident volume — the same "short, structured,
retrieval-grounded task, not one that needs frontier-model reasoning"
reasoning docs/IMPLEMENTATION_PLAN.md Section 7 gives for Haiku 4.5
applies here too.

tool_config forces the model to call exactly the one function defined
below (mode="ANY" + allowed_function_names) — Gemini's equivalent of
Anthropic's forced tool_choice, and just as required: see
app/rag/prompts.py's docstring for why a forced single tool is a
security property, not just a convenience, and that requirement doesn't
relax because the provider changed.
"""

import os

from google import genai
from google.genai import types

from app.rag.llm import RootCauseAnalysis
from app.rag.prompts import (
    ROOT_CAUSE_TOOL_DESCRIPTION,
    ROOT_CAUSE_TOOL_NAME,
    ROOT_CAUSE_TOOL_SCHEMA,
)

MODEL = "gemini-flash-lite-latest"
MAX_OUTPUT_TOKENS = 1024

_FUNCTION_DECLARATION = types.FunctionDeclaration(
    name=ROOT_CAUSE_TOOL_NAME,
    description=ROOT_CAUSE_TOOL_DESCRIPTION,
    # A plain JSON Schema dict, not types.Schema — parameters_json_schema
    # accepts the schema verbatim, so app/rag/prompts.py's schema is used
    # as-is instead of being re-expressed in the SDK's own Schema type.
    parameters_json_schema=ROOT_CAUSE_TOOL_SCHEMA,
)

_TOOL_CONFIG = types.ToolConfig(
    function_calling_config=types.FunctionCallingConfig(
        mode=types.FunctionCallingConfigMode.ANY,
        allowed_function_names=[ROOT_CAUSE_TOOL_NAME],
    )
)


class GeminiRootCauseLLM:
    def __init__(self) -> None:
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        return self._client

    async def generate(self, system_prompt: str, user_message: str) -> RootCauseAnalysis:
        response = await self._get_client().aio.models.generate_content(
            model=MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                tools=[types.Tool(function_declarations=[_FUNCTION_DECLARATION])],
                tool_config=_TOOL_CONFIG,
            ),
        )

        function_calls = response.function_calls
        if not function_calls:
            raise ValueError(f"Gemini response had no forced function call: {response!r}")
        return RootCauseAnalysis.model_validate(function_calls[0].args)
