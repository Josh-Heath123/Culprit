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
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bsk-[A-Za-z0-9]{20,}"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.",
    re.IGNORECASE,
)


def looks_like_credential(text: str) -> bool:
    return _CREDENTIAL.search(text) is not None
