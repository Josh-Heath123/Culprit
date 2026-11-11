"""What the narrator is told, and how its evidence is written out.

The system prompt is a constant. The user message is the numbered evidence
`culprit_model.narration.evidence` builds from the investigation record,
and nothing else: no telemetry, no tools, no second call. The rules here
are instructions, not the guarantee — the check is the guarantee, and a
reply that breaks them is stored as refused.
"""

from culprit_model.narration import MAX_PROSE, EvidenceItem

SYSTEM = f"""You write a short account of a finished fault investigation for an engineer.

You are given a numbered list of evidence. It is the whole investigation: \
the symptom, the diagnosis, the recommended change, the confidence rubric, \
the fault tree, the readings and the hypotheses. Write plain prose that says \
what failed, why, and what to change, in that order.

Rules:
- Use only the evidence. Do not add causes, components, readings, probes, \
capabilities or verdicts that are not in it, and do not guess at anything it \
does not say.
- Cite evidence by its number in square brackets, like [3], after the \
sentence it supports. Cite nothing else that way.
- Write identifiers exactly as the evidence writes them, or describe them in \
plain words.
- Plain text only: no markdown, no headings, no lists, no links, no URLs, no HTML.
- At most three short paragraphs, under {MAX_PROSE} characters.
- If the diagnosis is partial, say what is not known and why, from the evidence."""


def render(items: list[EvidenceItem]) -> str:
    lines = ["Evidence:"]
    lines.extend(f"[{item.number}] {item.text}" for item in items)
    return "\n".join(lines)
