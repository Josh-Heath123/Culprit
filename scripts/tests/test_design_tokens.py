"""Every text-and-background pair in frontend/src/index.css meets WCAG 2.2
AA (Phase 32.1, field 13); every boundary and the focus ring reach 3:1; and
neither the culprit's lime nor the brand's violet can be taken for a
status colour (DELIVERY_PLAN I2, I7; Phase 40 part 1).

The tokens are read out of the stylesheet itself, never re-typed here, so
changing a colour in index.css is what this test checks. The pairs are
built from the token *names*, not listed by hand: every text token (`--fg*`,
the accents, every status colour) is checked against every surface, so a
text token added tomorrow is checked the day it exists — and a surface
too.

AA for body text is 4.5:1. Nothing in the interface is large enough to
claim the 3:1 large-text allowance consistently, so 4.5 is held
everywhere. Non-text contrast (WCAG 1.4.11) is 3:1: a control's boundary
and the focus ring.
"""

import colorsys
import re
from pathlib import Path

import pytest

RGBA = tuple[float, float, float, float]

INDEX_CSS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "index.css"
AA = 4.5
NON_TEXT = 3.0

#: Text tokens drawn on surfaces. `culprit` is lime as text: the root's
#: label and the diagnosis line.
TEXT = ("fg", "fg-muted", "fg-subtle", "brand", "culprit")
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
#: Opaque surfaces, from the well up.
SURFACES = ("surface-sunken", "surface-0", "surface-1", "surface-2", "surface-3")
#: Translucent surfaces, composited over the page before measuring.
GLASS = ("glass",)
#: Boundaries that identify a control: 3:1 on every surface and on glass.
BOUNDARIES = ("line-strong",)
#: Where a focusable element sits, and so where its offset ring is drawn:
#: the well, the page, a panel, glass. surface-2 and surface-3 are inner
#: items and hover states, under an element and never under its ring.
RING_SURFACES = ("surface-sunken", "surface-0", "surface-1", "glass")
#: The identity colours no status may be mistaken for (I2): the culprit's
#: lime, and the brand's violet as fill and as text.
IDENTITY = ("culprit", "brand-fill", "brand")
#: A status colour must sit this far round the hue wheel from each, unless
#: it is a grey (saturation under GREY), which no one reads as lime or
#: violet. Lime's hue is 72 degrees, violet's 258.
MIN_HUE_DISTANCE = 30.0
GREY = 0.25


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
    for tint in ("brand-tint", "culprit-tint"):
        under = colour[tint]
        pairs.append(("fg", tint, contrast(colour["fg"], under)))
        accent = tint.removesuffix("-tint")
        pairs.append((accent, tint, contrast(colour[accent], under)))
    for fill in ("brand-fill", "brand-fill-hover", "selection"):
        pairs.append(("on-brand-fill", fill, contrast(colour["on-brand-fill"], colour[fill])))
    # Lime as a filled block, with plum on it (I2).
    pairs.append(("on-culprit", "culprit", contrast(colour["on-culprit"], colour["culprit"])))
    return pairs


def _non_text_pairs(tokens: dict[str, str]) -> list[tuple[str, str, float]]:
    colour = {name: _rgba(_resolve(tokens, name)) for name in tokens if _is_colour(tokens, name)}
    page = colour["surface-0"]
    backgrounds = {name: colour[name] for name in SURFACES}
    for name in GLASS:
        backgrounds[name] = _over(colour[name], page)
    pairs = [
        (boundary, background, contrast(colour[boundary], value))
        for boundary in BOUNDARIES
        for background, value in backgrounds.items()
    ]
    pairs += [("ring", name, contrast(colour["ring"], backgrounds[name])) for name in RING_SURFACES]
    return pairs


def hue_and_saturation(colour: RGBA) -> tuple[float, float]:
    hue, _lightness, saturation = colorsys.rgb_to_hls(*(c / 255 for c in colour[:3]))
    return hue * 360, saturation


def hue_distance(a: float, b: float) -> float:
    gap = abs(a - b) % 360
    return min(gap, 360 - gap)


def mistakable(status: RGBA, identity: RGBA) -> bool:
    """A status colour a reader could take for an identity colour: a
    chromatic one within MIN_HUE_DISTANCE of its hue."""
    status_hue, status_saturation = hue_and_saturation(status)
    identity_hue, _ = hue_and_saturation(identity)
    if status_saturation < GREY:
        return False
    return hue_distance(status_hue, identity_hue) < MIN_HUE_DISTANCE


def _is_colour(tokens: dict[str, str], name: str) -> bool:
    try:
        value = _resolve(tokens, name)
    except KeyError:
        return False
    return value.startswith("#") or value.startswith("rgb")


TOKENS = _root_tokens(INDEX_CSS.read_text(encoding="utf-8"))
PAIRS = _pairs(TOKENS)
NON_TEXT_PAIRS = _non_text_pairs(TOKENS)


@pytest.mark.parametrize(
    ("text", "background", "ratio"), PAIRS, ids=[f"{t}-on-{b}" for t, b, _ in PAIRS]
)
def test_every_text_and_background_pair_meets_aa(text: str, background: str, ratio: float) -> None:
    assert ratio >= AA, f"--{text} on --{background} is {ratio:.2f}:1, below WCAG AA {AA}:1"


@pytest.mark.parametrize(
    ("token", "background", "ratio"),
    NON_TEXT_PAIRS,
    ids=[f"{t}-on-{b}" for t, b, _ in NON_TEXT_PAIRS],
)
def test_every_boundary_and_the_focus_ring_reach_three_to_one(
    token: str, background: str, ratio: float
) -> None:
    assert ratio >= NON_TEXT, f"--{token} on --{background} is {ratio:.2f}:1, below {NON_TEXT}:1"


@pytest.mark.parametrize(("status", "identity"), [(s, i) for s in STATUS for i in IDENTITY])
def test_no_status_colour_can_be_taken_for_lime_or_violet(status: str, identity: str) -> None:
    """I7: lime means the answer and violet means interaction, so no verdict
    or severity may sit near either on the hue wheel."""
    status_colour = _rgba(_resolve(TOKENS, status))
    identity_colour = _rgba(_resolve(TOKENS, identity))
    status_hue, saturation = hue_and_saturation(status_colour)
    identity_hue, _ = hue_and_saturation(identity_colour)
    assert not mistakable(status_colour, identity_colour), (
        f"--{status} (hue {status_hue:.0f}, saturation {saturation:.2f}) is within "
        f"{MIN_HUE_DISTANCE:.0f} degrees of --{identity} (hue {identity_hue:.0f})"
    )


def test_the_anchors_are_the_identity() -> None:
    """I2's four anchors, exactly: the page, the text, violet for fills and
    the ring, lime for the culprit."""
    assert _resolve(TOKENS, "surface-0").lower() == "#221331"
    assert _resolve(TOKENS, "fg").lower() == "#fdfdfd"
    assert _resolve(TOKENS, "brand-fill").lower() == "#7540f5"
    assert _resolve(TOKENS, "ring").lower() == "#7540f5"
    assert _resolve(TOKENS, "culprit").lower() == "#d6fa4a"


def test_the_surfaces_are_plum_at_other_lightnesses() -> None:
    """I2: surfaces are derived from plum by lightness alone, one darker
    for wells and steps lighter for panels."""
    plum_hue, plum_saturation = hue_and_saturation(_rgba(_resolve(TOKENS, "surface-0")))
    lightness = []
    for name in SURFACES:
        colour = _rgba(_resolve(TOKENS, name))
        hue, saturation = hue_and_saturation(colour)
        assert hue_distance(hue, plum_hue) < 3, f"--{name} is not plum's hue"
        assert abs(saturation - plum_saturation) < 0.03, f"--{name} is not plum's saturation"
        lightness.append(colorsys.rgb_to_hls(*(c / 255 for c in colour[:3]))[1])
    assert lightness == sorted(lightness), "the surfaces are not in order from the well up"


def test_every_status_has_a_tint_and_a_line() -> None:
    for status in STATUS:
        for suffix in ("", "-tint", "-line"):
            assert f"{status}{suffix}" in TOKENS, f"--{status}{suffix} is missing"


def test_no_text_token_escapes_the_check() -> None:
    """A text token the pair list does not name would go unmeasured. Every
    token that is not a surface, a line, a tint or a fill must be one of
    TEXT or STATUS. (Since Phase 32.1 part 2 there are no shadcn aliases
    left to exempt.)"""
    checked = set(TEXT) | set(STATUS) | set(BOUNDARIES) | {"on-brand-fill", "on-culprit", "ring"}
    structural = re.compile(
        r"^(surface-(\d|sunken)|glass(-line)?|scrim|line|.*-tint|.*-line|brand-fill(-hover)?|selection"
        r"|graticule(-mark)?|glow-violet|radius-\d|shadow-\d|shadow-culprit-glow)$"
    )
    unchecked = sorted(
        name for name in TOKENS if name not in checked and not structural.match(name)
    )
    assert unchecked == [], f"tokens with no contrast check: {unchecked}"


def test_the_hue_check_fails_a_status_near_lime_or_violet() -> None:
    """Mutation: the old degrades yellow (#f2d75b, hue 50) is 22 degrees from
    lime, and the old inconclusive lavender (#b9a6ff, hue 253) 5 from violet."""
    lime, violet = _rgba("#d6fa4a"), _rgba("#7540f5")
    assert mistakable(_rgba("#f2d75b"), lime)
    assert mistakable(_rgba("#b9a6ff"), violet)
    assert not mistakable(_rgba("#b6a9c6"), violet), "a plum-grey is not violet"


def test_the_check_fails_a_pair_below_aa() -> None:
    """Mutation: the measure itself must be able to fail. Mid-grey on
    midnight is about 3:1."""
    assert contrast(_rgba("#5a6070"), _rgba("#05070c")) < AA
    assert contrast(_rgba("#ffffff"), _rgba("#000000")) == pytest.approx(21.0)
