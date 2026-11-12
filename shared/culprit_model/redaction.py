"""Whether free text carries something credential-shaped.

The Python half of `cli/internal/model/redact.go`, with the same patterns.
Used to refuse a capture bundle whose skip reasons, refusal reasons or
`meta` values carry a connection string or a key — text the CLI never
writes, because it builds those from closed vocabulary, but that anyone
can put into a capture file by hand and re-hash (the Phase 30 phase audit
did exactly that). Standing invariant 11: error text is output.

Unanchored: a credential inside a sentence is still a credential.
Deterministic and dependency-free.
"""

import re

_CREDENTIAL = re.compile(
    r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"
    r"|[a-z][a-z0-9+.-]*://\S*[?&](password|passwd|secret|token|api[_-]?key)=[^&\s]*"
    # The whole block, to its end or the end of the text, as Go removes it.
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----(?s:.*?)(-----END [A-Z ]*PRIVATE KEY-----|\Z)"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bsk-[A-Za-z0-9]{20,}"
    # Anthropic's keys (sk-ant-api03-...): hyphens break the pattern above.
    r"|\bsk-ant-[A-Za-z0-9_-]{20,}"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
    # Phase 37 part 1, before any statement text is read: a password outside
    # a URL (libpq's keyword form, a literal in a statement), Slack tokens,
    # and user:pass@host with no scheme. Each is a case in
    # shared/tests/redaction_conformance.json.
    r"""|\b(password|passwd|pwd)\s*=\s*('[^']*'|"[^"]*"|[^\s&;,'"]+)"""
    r"|\bxox[abposr]-[A-Za-z0-9-]{10,}"
    r"|\bxapp-[0-9]+-[A-Za-z0-9-]{10,}"
    r"|\b[A-Za-z0-9._%+-]+:[^\s/@:]+@",
    re.IGNORECASE,
)


def looks_like_credential(text: str) -> bool:
    return _CREDENTIAL.search(text) is not None


def redact_credentials(text: str) -> str:
    """Replace anything credential-shaped with a marker.

    The Python half of `model.RedactCredentials` in Go, with the same
    marker so a redacted string reads identically whichever side produced
    it. Detection alone was enough while the only use was *refusing* a
    capture; Phase 31 needs the replacing form, because a reading
    legitimately carries a caller's URL and the credential inside it has
    to come out rather than take the whole reading with it.
    """
    return _CREDENTIAL.sub("[redacted]", text)
