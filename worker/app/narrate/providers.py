"""The providers, behind one interface: one call, a system prompt and one
user message in, text out. No tools are offered, and nothing is streamed.

Both speak plain HTTP through httpx — the client already in the worker's
lockfile (field 11: no new dependency) — so the stub CI points the
`ollama` provider at runs the same request code a real one does.

**Errors are built from a closed vocabulary.** A provider's error body is
never read into a reason: it is text from outside, and a stub in CI puts a
secret-looking string there on purpose to prove it leaves no trace. A
reason names the provider, the HTTP status or the kind of failure, and
then passes `redact_credentials` before it is stored (standing
invariant 11).
"""

from typing import Any, Protocol

import httpx

from app.narrate.config import NarratorConfig

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
#: Room for the model's own reasoning as well as the prose; the prose is
#: held to MAX_PROSE characters after.
MAX_TOKENS = 16000


class ProviderError(Exception):
    """An attempt that failed. `reason` is closed-vocabulary text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Provider(Protocol):
    name: str
    model: str

    async def complete(self, system: str, user: str) -> str: ...


def _http_failure(provider: str, exc: httpx.HTTPError) -> ProviderError:
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(f"{provider} did not answer in time")
    if isinstance(exc, httpx.HTTPStatusError):
        return ProviderError(f"{provider} answered HTTP {exc.response.status_code}")
    return ProviderError(f"{provider} could not be reached ({type(exc).__name__})")


async def _post(
    provider: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, transport=transport
        ) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            parsed = response.json()
    except httpx.HTTPError as exc:
        raise _http_failure(provider, exc) from None
    except ValueError:
        raise ProviderError(f"{provider} answered with something that is not JSON") from None
    if not isinstance(parsed, dict):
        raise ProviderError(f"{provider} answered in a shape it does not use")
    return parsed


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self, config: NarratorConfig, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.model = config.model
        self._key = config.api_key
        self._timeout = config.timeout_seconds
        # Tests only: what the request would be, with no network.
        self._transport = transport

    async def complete(self, system: str, user: str) -> str:
        reply = await _post(
            self.name,
            ANTHROPIC_URL,
            {
                "x-api-key": self._key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            {
                "model": self.model,
                "max_tokens": MAX_TOKENS,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            self._timeout,
            self._transport,
        )
        stop = reply.get("stop_reason")
        if stop == "refusal":
            raise ProviderError("anthropic declined to answer (refusal)")
        if stop == "max_tokens":
            raise ProviderError("anthropic's reply was cut off at its token limit")
        blocks = reply.get("content")
        if not isinstance(blocks, list):
            raise ProviderError("anthropic answered in a shape it does not use")
        return "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )


class OllamaProvider:
    """A model on the operator's own machine: no key, nothing leaves it."""

    name = "ollama"

    def __init__(self, config: NarratorConfig) -> None:
        self.model = config.model
        self._url = f"{config.ollama_url}/api/chat"
        self._timeout = config.timeout_seconds

    async def complete(self, system: str, user: str) -> str:
        reply = await _post(
            self.name,
            self._url,
            {"content-type": "application/json"},
            {
                "model": self.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            self._timeout,
        )
        message = reply.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ProviderError("ollama answered in a shape it does not use")
        return message["content"]


def build(config: NarratorConfig) -> Provider | None:
    if config.provider == "anthropic":
        return AnthropicProvider(config)
    if config.provider == "ollama":
        return OllamaProvider(config)
    return None
