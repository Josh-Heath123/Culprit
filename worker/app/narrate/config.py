"""The narrator's settings — the operator's, in `.env.prod`.

`LLM_PROVIDER` is `none` (the default: nothing is narrated), `anthropic`
or `ollama`. With a provider, `NARRATOR_MODEL` is required, and so is
`ANTHROPIC_API_KEY` for anthropic or `OLLAMA_URL` for ollama. Nothing here
has a default model or address: which model reads an investigation, and
where it runs, is the operator's choice, made in their own file.

Read when the worker starts, and refused loudly if half-set: a provider
with no model is not "off".
"""

import os
from dataclasses import dataclass

PROVIDERS = ("none", "anthropic", "ollama")

#: One call per attempt, bounded. A timeout is a failed attempt.
DEFAULT_TIMEOUT_SECONDS = 60.0
#: How long after a failed or refused attempt the next may be made.
DEFAULT_RETRY_SECONDS = 60.0


class NarratorConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class NarratorConfig:
    provider: str
    model: str = ""
    api_key: str = ""
    ollama_url: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    retry_seconds: float = DEFAULT_RETRY_SECONDS

    @property
    def enabled(self) -> bool:
        return self.provider != "none"


def from_env(environ: "os._Environ[str] | dict[str, str]" = os.environ) -> NarratorConfig:
    provider = (environ.get("LLM_PROVIDER") or "none").strip().lower()
    if provider not in PROVIDERS:
        raise NarratorConfigError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}")
    if provider == "none":
        return NarratorConfig(provider="none")
    model = (environ.get("NARRATOR_MODEL") or "").strip()
    if not model:
        raise NarratorConfigError(f"LLM_PROVIDER={provider} needs NARRATOR_MODEL")
    timeout = float(environ.get("NARRATOR_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
    retry = float(environ.get("NARRATOR_RETRY_SECONDS") or DEFAULT_RETRY_SECONDS)
    if provider == "anthropic":
        key = (environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not key:
            raise NarratorConfigError("LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
        return NarratorConfig(
            provider=provider,
            model=model,
            api_key=key,
            timeout_seconds=timeout,
            retry_seconds=retry,
        )
    url = (environ.get("OLLAMA_URL") or "").strip().rstrip("/")
    if not url:
        raise NarratorConfigError("LLM_PROVIDER=ollama needs OLLAMA_URL")
    return NarratorConfig(
        provider=provider,
        model=model,
        ollama_url=url,
        timeout_seconds=timeout,
        retry_seconds=retry,
    )
