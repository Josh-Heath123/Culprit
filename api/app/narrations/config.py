"""Whether narration is on — the operator's `LLM_PROVIDER`, in `.env.prod`.

The API never talks to a provider; only the worker's narrator does
(`app.narrate`, behind a `lint-imports` contract). The API reads the
setting so the investigation page can say "narration is off" rather than
"not narrated yet" when nothing will ever narrate. `none` is the default
(D8): every command and page is complete without prose.
"""

import os

PROVIDERS = ("none", "anthropic", "ollama")

NARRATION_PROVIDER = (os.environ.get("LLM_PROVIDER") or "none").strip().lower()
if NARRATION_PROVIDER not in PROVIDERS:
    # Loud, at startup: a misspelt provider is not "off".
    raise RuntimeError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}")
