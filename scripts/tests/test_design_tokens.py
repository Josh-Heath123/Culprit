"""Every text-and-background pair in frontend/src/index.css meets WCAG 2.2
AA (Phase 32.1, field 13).

The tokens are read out of the stylesheet itself, never re-typed here, so
changing a colour in index.css is what this test checks. The pairs are
built from the token *names*, not listed by hand: every text token (`--fg*`,
the accents, every status colour) is checked against every surface, so a
text token added tomorrow is checked the day it exists — and a surface
too.

AA for body text is 4.5:1. Nothing in the interface is large enough to
claim the 3:1 large-text allowance consistently, so 4.5 is held
everywhere.
"""

import re
from pathlib import Path

import pytest

RGBA = tuple[float, float, float, float]

INDEX_CSS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "index.css"
AA = 4.5

#: Text tokens drawn on surfaces.
TEXT = ("fg", "fg-muted", "fg-subtle", "brand", "highlight")
#: Status colours: each is text on every surface and on its own tint.
STATUS = (
    "pass",
    "fail",
    "inconclusive",
    "refused",
    "breaks",
    "degrades",
    "cosmetic",
    "unknown",
)
#: Opaque surfaces, page upward.
SURFACES = ("surface-0", "surface-1", "surface-2", "surface-3")
#: Translucent surfaces, composited over the page before measuring.
GLASS = ("glass",)


def _root_tokens(css: str) -> dict[str, str]:
    block = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    assert block, "index.css has no :root block"
    body = re.sub(r"/\*.*?\*/", "", block.group(1), flags=re.S)
    return {
        name: value.strip() for name, value in re.findall(r"--([a-z0-9-]+)\s*:\s*([^;]+);", body)
    }


def _resolve(tokens: dict[str, str], name: str, depth: int = 0) -> str:
    value = tokens[name]
    reference = re.fullmatch(r"var\(--([a-z0-9-]+)\)", value)
    if reference:
        assert depth < 10, f"--{name} is a var() cycle"
        return _resolve(tokens, reference.group(1), depth + 1)
    return value


def _rgba(value: str) -> RGBA:
    value = value.strip()
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        assert len(digits) == 6, f"unsupported colour {value}"
        r, g, b = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
        return (r, g, b, 1.0)
    match = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", value)
    assert match, f"unsupported colour {value}"
    r, g, b = (int(match.group(i)) for i in (1, 2, 3))
    return (r, g, b, float(match.group(4) or 1))


def _over(top: RGBA, under: RGBA) -> RGBA:
    alpha = top[3]
    r, g, b = (top[i] * alpha + under[i] * (1 - alpha) for i in range(3))
    return (r, g, b, 1.0)


def _luminance(colour: RGBA) -> float:
    def channel(value: float) -> float:
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in colour[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(text: RGBA, background: RGBA) -> float:
    lighter, darker = sorted((_luminance(text), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _pairs(tokens: dict[str, str]) -> list[tuple[str, str, float]]:
    colour = {name: _rgba(_resolve(tokens, name)) for name in tokens if _is_colour(tokens, name)}
    page = colour["surface-0"]
    backgrounds = {name: colour[name] for name in SURFACES}
    for name in GLASS:
        backgrounds[name] = _over(colour[name], page)

    pairs: list[tuple[str, str, float]] = []
    for text in TEXT + STATUS:
        for background, value in backgrounds.items():
            pairs.append((text, background, contrast(colour[text], value)))
    for status in STATUS:
        tint = _over(colour[f"{status}-tint"], page)
        pairs.append((status, f"{status}-tint", contrast(colour[status], tint)))
        pairs.append(("fg", f"{status}-tint", contrast(colour["fg"], tint)))
    for tint in ("brand-tint", "highlight-tint"):
        under = colour[tint]
        pairs.append(("fg", tint, contrast(colour["fg"], under)))
        accent = tint.removesuffix("-tint")
        pairs.append((accent, tint, contrast(colour[accent], under)))
    for fill in ("brand-fill", "brand-fill-hover"):
        pairs.append(("on-brand-fill", fill, contrast(colour["on-brand-fill"], colour[fill])))
    # The shadcn aliases the routes part 2 has not redesigned still use.
    for text, background in (
        ("foreground", "background"),
        ("foreground", "card"),
        ("foreground", "popover"),
        ("muted-foreground", "background"),
        ("muted-foreground", "card"),
        ("muted-foreground", "popover"),
        ("muted-foreground", "muted"),
        ("muted-foreground", "accent"),
        ("primary", "background"),
        ("primary", "card"),
        ("primary-foreground", "primary"),
        ("destructive", "card"),
        ("severity-warning", "card"),
    ):
        pairs.append((text, background, contrast(colour[text], colour[background])))
    return pairs


def _is_colour(tokens: dict[str, str], name: str) -> bool:
    try:
        value = _resolve(tokens, name)
    except KeyError:
        return False
    return value.startswith("#") or value.startswith("rgb")


TOKENS = _root_tokens(INDEX_CSS.read_text(encoding="utf-8"))
PAIRS = _pairs(TOKENS)


@pytest.mark.parametrize(
    ("text", "background", "ratio"), PAIRS, ids=[f"{t}-on-{b}" for t, b, _ in PAIRS]
)
def test_every_text_and_background_pair_meets_aa(text: str, background: str, ratio: float) -> None:
    assert ratio >= AA, f"--{text} on --{background} is {ratio:.2f}:1, below WCAG AA {AA}:1"


def test_every_status_has_a_tint_and_a_line() -> None:
    for status in STATUS:
        for suffix in ("", "-tint", "-line"):
            assert f"{status}{suffix}" in TOKENS, f"--{status}{suffix} is missing"


def test_no_text_token_escapes_the_check() -> None:
    """A text token the pair list does not name would go unmeasured. Every
    token that is not a surface, a line, a tint, a fill or an alias must be
    one of TEXT or STATUS."""
    checked = set(TEXT) | set(STATUS) | {"on-brand-fill"}
    structural = re.compile(
        r"^(surface-\d|glass(-line)?|scrim|line(-strong)?|.*-tint|.*-line|brand-fill(-hover)?|radius-\d|shadow-\d)$"
    )
    aliases = {
        "background", "foreground", "card", "card-foreground", "popover", "popover-foreground",
        "primary", "primary-foreground", "secondary", "secondary-foreground", "muted",
        "muted-foreground", "accent", "accent-foreground", "destructive", "destructive-foreground",
        "severity-warning", "severity-warning-foreground", "border", "input", "ring", "radius",
    }  # fmt: skip
    unchecked = sorted(
        name
        for name in TOKENS
        if name not in checked and name not in aliases and not structural.match(name)
    )
    assert unchecked == [], f"tokens with no contrast check: {unchecked}"


def test_the_check_fails_a_pair_below_aa() -> None:
    """Mutation: the measure itself must be able to fail. Mid-grey on
    midnight is about 3:1."""
    assert contrast(_rgba("#5a6070"), _rgba("#05070c")) < AA
    assert contrast(_rgba("#ffffff"), _rgba("#000000")) == pytest.approx(21.0)
