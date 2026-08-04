"""Pure text sanitization for untrusted content reaching the LLM prompt.

No I/O, no imports beyond the standard library. Per CLAUDE.md and Phase
6's own scope text, retrieved postmortem text and log snippets pulled
from raw_events are untrusted input — the ingest-gateway (Phase 3)
validates shape, never message contents — so this module exists as the
one place that requirement is actually enforced, kept trivial to
unit-test in isolation from any network call.
"""

_OPEN_TAG_TMPL = "<untrusted-{label}>"
_CLOSE_TAG_TMPL = "</untrusted-{label}>"


def truncate(text: str, max_chars: int) -> str:
    """A hard character cap, not a token cap — cheap, deterministic, and
    enough to bound both LLM cost and prompt-injection surface (a
    truncated instruction is far less likely to parse as a complete
    one)."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + " …[truncated]"


def _strip_delimiter_collisions(text: str, label: str) -> str:
    """Untrusted content must not be able to fabricate its own closing
    delimiter and "escape" the block early. Stripping any literal
    occurrence of this block's own tags is a cheap, sufficient guard for
    a fixed, known tag format — this is not a general HTML/XML sanitizer,
    and the content is never rendered or parsed as markup, only read by
    the model as plain text.
    """
    open_tag = _OPEN_TAG_TMPL.format(label=label)
    close_tag = _CLOSE_TAG_TMPL.format(label=label)
    return text.replace(open_tag, "").replace(close_tag, "")


def delimit_untrusted(label: str, text: str, max_chars: int) -> str:
    """Truncate, strip delimiter collisions, then wrap in a tag pair
    that's structurally distinct from the system prompt's own
    instructions, so nothing inside this block is ever mistaken for an
    instruction from Culprit itself. The system prompt (see
    app/rag/prompts.py) explicitly tells the model to treat everything
    inside these tags as data, never as instructions — this function is
    the other half of that contract: it's what actually bounds the
    content's size and strips any attempt to fake a block boundary.
    """
    cleaned = _strip_delimiter_collisions(truncate(text, max_chars), label)
    open_tag = _OPEN_TAG_TMPL.format(label=label)
    close_tag = _CLOSE_TAG_TMPL.format(label=label)
    return f"{open_tag}\n{cleaned}\n{close_tag}"
