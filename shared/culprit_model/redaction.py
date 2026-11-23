# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: Apache-2.0

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

# Phase 44 batch 1 (F44-002): the pattern's coverage is exactly the rows of
# shared/tests/redaction_conformance.json, which Go's redact.go is held to as
# well; a shape not there is not promised (docs/SECURITY.md §8).
#
# A key whose name has a credential word as one of its parts (DB_PASSWORD,
# x-auth-token, spring.datasource.password, "api_key"), in any case. The key
# and its separator are kept and only the value goes, so a subject or a probe
# id is never removed with it. A colon counts only when quoted (JSON), or
# for a YAML key: no dots, starting the text or a line, or after {, a
# comma, (, [ or a quote, and followed by whitespace. So `auth:a->b/audience` is a
# subject and `probe.auth.token_shape: no token ...` a probe id, not keys.
_WORD = (
    r"(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key"
    r"|private[_-]?key|credentials?|auth)"
)
_KEY = r"\b(?:[a-z0-9]+[_.-])*" + _WORD + r"(?:[_.-][a-z0-9]+)*"
_YAML_KEY = r"""(?:^|[\n{,(\['"])[ \t]*(?:[a-z0-9]+[_-])*""" + _WORD + r"(?:[_-][a-z0-9]+)*"
_VALUE = r"""(?:'[^']*'|"[^"]*"|[^\s&;,'"}]+)"""
# A Bearer or Basic credential: a run with an upper-case letter, a digit or
# base64 punctuation after its third character, so "Bearer token" and
# "basic authentication" stay words.
_OPAQUE = r"[a-z0-9._~+/-]{3,}(?-i:[A-Z0-9+/=])[a-z0-9._~+/=-]*"

_CREDENTIAL = re.compile(
    r"(?P<key>" + _KEY + r"""(?:\s*=\s*|["']\s*:\s*))""" + _VALUE
    + r"|(?P<yaml>" + _YAML_KEY + r"\s*:\s+)" + _VALUE
    + r"""|(?P<authz>\b(?:proxy-)?authorization["']?\s*[=:]\s*)(?:[a-z]+\s+)?[^\s,;'"]+"""
    + r"|(?P<scheme>\b(?:bearer|basic)\s+)" + _OPAQUE
    # URL userinfo, an empty user included (redis://:pw@), the password
    # running to the last @ before the host.
    + r"|[a-z][a-z0-9+.-]*://[^/\s:@]*:[^\s/?#]*@"
    # The whole block, to its end or the end of the text, as Go removes it.
    + r"|-----BEGIN [A-Z ]*PRIVATE KEY-----(?s:.*?)(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"
    # Provider formats.
    + r"|\bAKIA[0-9A-Z]{16}\b"
    + r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    + r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
    + r"|\bglpat-[A-Za-z0-9_-]{20,}"
    + r"|\bsk_(?:live|test)_[A-Za-z0-9]{10,}"
    + r"|\bAIza[0-9A-Za-z_-]{35}"
    + r"|\bsk-[A-Za-z0-9]{20,}"
    # Anthropic's keys (sk-ant-api03-...): hyphens break the pattern above.
    + r"|\bsk-ant-[A-Za-z0-9_-]{20,}"
    # A JWT, its signature included.
    + r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*"
    + r"|\bxox[a-z]-[A-Za-z0-9-]{10,}"
    + r"|\bxapp-[0-9]+-[A-Za-z0-9-]{10,}"
    # user:pass@host with no scheme (Phase 37 part 1).
    + r"|\b[A-Za-z0-9._%+-]+:[^\s/@:]+@"
    # SQL's own form: CREATE/ALTER ROLE or USER ... PASSWORD '...', which
    # pg_stat_statements keeps verbatim for a utility statement.
    + r"|\bPASSWORD\s+'[^']*'",
    re.IGNORECASE,
)


def _marker(match: re.Match[str]) -> str:
    kept = (
        match.group("key")
        or match.group("yaml")
        or match.group("authz")
        or match.group("scheme")
        or ""
    )
    return kept + "[redacted]"


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
    return _CREDENTIAL.sub(_marker, text)
