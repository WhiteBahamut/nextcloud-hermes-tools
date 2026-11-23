"""Contrast guard for the dashboard tab stylesheet (dashboard/dist/style.css).

Pins the nord dashboard theme tokens and asserts WCAG AA contrast (>= 4.5:1 for
text, >= 3:1 for the non-text status signals) for every text-bearing selector
the theme review flagged, plus a 0.75 rem font-size floor. A theme token change
or a regression in the stylesheet fails here instead of in the live dashboard.

Pure stdlib, fully offline: the CSS is parsed with regexes, var()/color-mix()
values are resolved against the pinned token map, and ratios are computed with
the WCAG relative-luminance formula. No sockets, no plugin imports.

The Hermes host ships `code { background: var(--selection-bg, var(--midground));
color: var(--background) }` inside @layer base.
test_code_elements_aa_with_host_base_rule models that layered rule on top of
the plugin stylesheet (layered rules lose to any unlayered rule, then
specificity/order decide within the unlayered set), so the <code> param and
signature elements are checked with the host chip in play — not just against
the plugin CSS alone, which cannot see element selectors.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS_PATH = Path(__file__).resolve().parent.parent / "dashboard" / "dist" / "style.css"

# Pinned nord theme tokens (dashboard-themes/nord.yaml): the eight semantic
# tokens supplied with the theme review, plus foreground #D8DEE9 (the 6.39:1-on-
# muted value the review quotes), destructive-foreground #ECEFF4 (the 3.55:1-on-
# destructive pair), and border #4C566A (nord3). Prefixed and unprefixed names
# both map, matching the var(--color-x, var(--x)) fallback chains in the CSS.
NORD: dict[str, str] = {
    "--color-background": "#2E3440",
    "--background": "#2E3440",
    "--color-foreground": "#D8DEE9",
    "--foreground": "#D8DEE9",
    "--color-card": "#3B4252",
    "--card": "#3B4252",
    "--color-card-foreground": "#D8DEE9",
    "--card-foreground": "#D8DEE9",
    "--color-muted": "#434C5E",
    "--muted": "#434C5E",
    "--color-muted-foreground": "#BCCCDC",
    "--muted-foreground": "#BCCCDC",
    "--color-success": "#A3BE8C",
    "--success": "#A3BE8C",
    "--color-warning": "#EBCB8B",
    "--warning": "#EBCB8B",
    "--color-destructive": "#BF616A",
    "--destructive": "#BF616A",
    "--color-destructive-foreground": "#ECEFF4",
    "--destructive-foreground": "#ECEFF4",
    "--color-primary": "#88C0D0",
    "--primary": "#88C0D0",
    "--color-border": "#4C566A",
    "--border": "#4C566A",
    "--color-ring": "#88C0D0",
    "--ring": "#88C0D0",
    # host base-layer tokens read by `code { background: var(--selection-bg,
    # var(--midground)) }` (nord8), pinned so the code-element test can
    # resolve the chip color
    "--selection-bg": "#D8DEE9",
    "--midground": "#D8DEE9",
}

AA_TEXT = 4.5
AA_NON_TEXT = 3.0
SIZE_FLOOR_REM = 0.75

# The whole tab lives on a host Card, so card is the page-level backdrop for
# chains that never reach a .nc-* element with its own background.
CARD = NORD["--color-card"]


# ---------- WCAG math ----------


def _luminance(hex_color: str) -> float:
    """Relative luminance per WCAG 2.x for a #rrggbb color."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two #rrggbb colors."""
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def srgb_mix(a: str, b: str, pct_a: float) -> str:
    """color-mix(in srgb, a pct%, b) for opaque colors: pct_a is a's share."""
    ha, hb = a.lstrip("#"), b.lstrip("#")
    p = pct_a / 100.0
    return "#" + "".join(
        f"{round(p * int(ha[i : i + 2], 16) + (1 - p) * int(hb[i : i + 2], 16)):02X}"
        for i in (0, 2, 4)
    )


# ---------- minimal CSS parsing ----------


def _split_top(text: str, sep: str = ",") -> list[str]:
    """Split on sep at paren depth 0 (var()/color-mix() nest)."""
    parts: list[str] = []
    depth = 0
    cur = ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts]


def parse_rules(css: str) -> list[tuple[int, str, dict[str, str]]]:
    """Flat (order, selector, {prop: value}) rules from a stylesheet.

    @media wrappers don't match the {..} pattern, so their inner rules are
    captured as top-level rules; none of them set color/background/font-size,
    which is all the checks below read.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules: list[tuple[int, str, dict[str, str]]] = []
    for order, m in enumerate(re.finditer(r"([^{}]+)\{([^{}]*)\}", css)):
        decls: dict[str, str] = {}
        for chunk in m.group(2).split(";"):
            if ":" in chunk:
                prop, value = chunk.split(":", 1)
                decls[prop.strip().lower()] = value.strip()
        rules.append((order, m.group(1).strip(), decls))
    return rules


def _compounds(selector: str) -> list[frozenset[str]] | None:
    """Descendant chain of class-only compounds, or None if unsupported.

    Selectors with pseudo-classes, combinators, element or universal parts are
    skipped — the checked properties never come from those rules.
    """
    parts: list[frozenset[str]] = []
    for part in selector.split():
        if any(ch in part for ch in ":>+~*"):
            return None
        if not part.startswith("."):
            return None
        parts.append(frozenset(part[1:].split(".")))
    return parts or None


def _matches(compounds: list[frozenset[str]], chain: list[frozenset[str]]) -> bool:
    """Descendant match of a selector chain against an element class chain."""
    if not compounds[-1] <= chain[-1]:
        return False
    idx = len(chain) - 2
    for comp in reversed(compounds[:-1]):
        while idx >= 0 and not comp <= chain[idx]:
            idx -= 1
        if idx < 0:
            return False
        idx -= 1
    return True


def cascade(rules: list[tuple[int, str, dict[str, str]]], chain: list[frozenset[str]]) -> dict[str, str]:
    """Final declarations for an element, by specificity then document order."""
    matched: list[tuple[int, int, dict[str, str]]] = []
    for order, selector, decls in rules:
        for sel in selector.split(","):
            compounds = _compounds(sel.strip())
            if compounds and _matches(compounds, chain):
                matched.append((sum(len(c) for c in compounds), order, decls))
                break
    matched.sort(key=lambda t: (t[0], t[1]))
    props: dict[str, str] = {}
    for _, _, decls in matched:
        props.update(decls)
    return props


def resolve_color(value: str, tokens: dict[str, str], backdrop: str) -> str:
    """Resolve a CSS color value (hex / var() chain / color-mix) to #rrggbb.

    ``transparent`` inside color-mix composites over ``backdrop``.
    """
    v = value.strip()
    if v.startswith("var("):
        inner = v[len("var(") : v.rindex(")")]
        parts = _split_top(inner)
        name = parts[0]
        if name in tokens:
            return tokens[name].lower()
        if len(parts) > 1:
            return resolve_color(parts[1], tokens, backdrop)
        raise ValueError(f"unknown token {name!r} in {value!r}")
    if v.startswith("color-mix("):
        inner = v[len("color-mix(") : v.rindex(")")]
        parts = _split_top(inner)
        a_color, a_pct = parts[1].rsplit(None, 1)
        b_raw = parts[2]
        a = resolve_color(a_color, tokens, backdrop)
        pct = float(a_pct.rstrip("%"))
        if b_raw == "transparent":
            return srgb_mix(a, backdrop, pct).lower()
        return srgb_mix(a, resolve_color(b_raw, tokens, backdrop), pct).lower()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return v.lower()
    if v == "transparent":
        return backdrop.lower()
    raise ValueError(f"unresolvable color value {value!r}")


def inherited_prop(
    rules: list[tuple[int, str, dict[str, str]]],
    chain: list[frozenset[str]],
    prop: str,
) -> str | None:
    """First declaration of prop walking the chain outward (color inherits)."""
    for i in range(len(chain) - 1, -1, -1):
        value = cascade(rules, chain[: i + 1]).get(prop)
        if value:
            return value
    return None


def effective_bg(
    rules: list[tuple[int, str, dict[str, str]]],
    chain: list[frozenset[str]],
    tokens: dict[str, str],
    page_bg: str,
) -> str:
    """First opaque background walking the chain outward, compositing mixes."""
    for i in range(len(chain) - 1, -1, -1):
        props = cascade(rules, chain[: i + 1])
        bg = props.get("background") or props.get("background-color")
        if bg:
            backdrop = effective_bg(rules, chain[:i], tokens, page_bg) if i > 0 else page_bg
            return resolve_color(bg, tokens, backdrop)
    return page_bg.lower()


def _rem(value: str) -> float:
    m = re.fullmatch(r"([0-9.]+)rem", value.strip())
    assert m, f"not a rem size: {value!r}"
    return float(m.group(1))


RULES = parse_rules(CSS_PATH.read_text(encoding="utf-8"))

# (name, element class chain root..target). Every text-bearing surface in the
# tab that the nord theme review measured.
TEXT_CASES: list[tuple[str, list[list[str]]]] = [
    ("stat value (base)", [["nc-stat"], ["nc-stat-value"]]),
    ("stat value ok-modifier", [["nc-stat", "nc-stat-ok"], ["nc-stat-value"]]),
    ("stat value warn-modifier", [["nc-stat", "nc-stat-warn"], ["nc-stat-value"]]),
    ("stat label", [["nc-stat"], ["nc-stat-label"]]),
    ("gate badge base", [["nc-list"], ["nc-row"], ["nc-gatebadge"]]),
    ("gate badge read/write tone", [["nc-list"], ["nc-row"], ["nc-gatebadge", "nc-gate-read"]]),
    ("gate badge destructive tone", [["nc-list"], ["nc-row"], ["nc-gatebadge", "nc-gate-destructive"]]),
    ("gate badge mixed tone", [["nc-list"], ["nc-row"], ["nc-gatebadge", "nc-gate-mixed"]]),
    ("param name", [["nc-param"], ["nc-param-name"]]),
    ("param type pill", [["nc-param"], ["nc-param-type"]]),
    ("param default", [["nc-param"], ["nc-param-default"]]),
    ("param description", [["nc-param"], ["nc-param-desc"]]),
    ("tool name", [["nc-list"], ["nc-row"], ["nc-name"]]),
    ("tool description", [["nc-list"], ["nc-row"], ["nc-desc"]]),
    ("group count pill", [["nc-group-head"], ["nc-group-count"]]),
    ("column header", [["nc-list"], ["nc-cols"]]),
    ("saving indicator", [["nc-list"], ["nc-row"], ["nc-saving"]]),
    ("toggle label", [["nc-list"], ["nc-row"], ["nc-toggle-label"]]),
    ("warning banner", [["nc-banner"]]),
    ("confirm text", [["nc-list"], ["nc-confirm"], ["nc-confirm-text"]]),
    ("detail description", [["nc-list"], ["nc-detail"], ["nc-detail-desc"]]),
    ("signature", [["nc-list"], ["nc-detail"], ["nc-signature"]]),
    ("help text", [["nc-help"], ["nc-help-text"]]),
    ("gate line", [["nc-gateline"]]),
    ("lede", [["nc-lede"]]),
    ("empty state", [["nc-list"], ["nc-empty"]]),
    ("nav panel search input", [["nc-nav"], ["nc-navrow"], ["nc-search"]]),
    ("nav row filter label", [["nc-nav"], ["nc-navrow"], ["nc-filterlabel"]]),
    ("filter pill", [["nc-nav"], ["nc-chip"]]),
    ("filter pill active", [["nc-nav"], ["nc-chip", "nc-chip-on"]]),
    ("list-bar result count", [["nc-listbar"], ["nc-count"]]),
    ("list-bar action pill", [["nc-listbar"], ["nc-action"]]),
]

# The host's base layer paints every <code> element with a chip:
# `code { background: var(--selection-bg, var(--midground)); color: var(--background) }`.
# Cascade layers make any unlayered rule beat it regardless of specificity, so on
# <code class="nc-param-name"> the plugin class always wins `color` while the chip
# `background` survives unless the plugin clears it — under nord that is #D8DEE9
# text on a #D8DEE9 chip (1:1, invisible). Pin the rule here so the guard sees it.
HOST_BASE_CODE: dict[str, str] = {
    "background": "var(--selection-bg, var(--midground))",
    "color": "var(--background)",
}


def cascade_with_host_base(
    rules: list[tuple[int, str, dict[str, str]]],
    chain: list[frozenset[str]],
) -> dict[str, str]:
    """Declarations on a <code> element: host @layer base first, then the
    unlayered plugin rules by specificity then document order."""
    props: dict[str, str] = dict(HOST_BASE_CODE)
    matched: list[tuple[int, int, dict[str, str]]] = []
    for order, selector, decls in rules:
        for sel in selector.split(","):
            compounds = _compounds(sel.strip())
            if compounds and _matches(compounds, chain):
                matched.append((sum(len(c) for c in compounds), order, decls))
                break
    matched.sort(key=lambda t: (t[0], t[1]))
    for _, _, decls in matched:
        props.update(decls)
    return props


# (name, element class chain root..target) for every <code> element the bundle
# renders (dist/index.js): the three param codes + the call signature.
CODE_CASES: list[tuple[str, list[list[str]]]] = [
    ("code param name", [["nc-param"], ["nc-param-name"]]),
    ("code param type", [["nc-param"], ["nc-param-type"]]),
    ("code param default", [["nc-param"], ["nc-param-default"]]),
    ("code signature", [["nc-list"], ["nc-detail"], ["nc-signature"]]),
]


@pytest.mark.parametrize("name,chain", TEXT_CASES, ids=[c[0] for c in TEXT_CASES])
def test_text_contrast_aa_under_nord(name: str, chain: list[list[str]]) -> None:
    """Every text selector must reach WCAG AA (4.5:1) under the pinned nord tokens."""
    fchain = [frozenset(c) for c in chain]
    color = inherited_prop(RULES, fchain, "color")
    assert color, f"{name}: no color resolvable on {chain[-1]}"
    fg = resolve_color(color, NORD, CARD)
    bg = effective_bg(RULES, fchain, NORD, CARD)
    ratio = contrast_ratio(fg, bg)
    assert ratio >= AA_TEXT, f"{name}: {ratio:.2f}:1 ({fg} on {bg}) < {AA_TEXT}:1"


@pytest.mark.parametrize("name,chain", CODE_CASES, ids=[c[0] for c in CODE_CASES])
def test_code_elements_aa_with_host_base_rule(name: str, chain: list[list[str]]) -> None:
    """Every <code> element must reach AA with the host's layered code rule in play.

    Without this, the guard only sees the plugin stylesheet and measures e.g. the
    param name as foreground on the .nc-param card (7.45:1 under nord) while the
    live host paints its own chip behind the text (1:1 under nord).
    """
    fchain = [frozenset(c) for c in chain]
    props = cascade_with_host_base(RULES, fchain)
    color = props.get("color") or inherited_prop(RULES, fchain, "color")
    assert color, f"{name}: no color resolvable on {chain[-1]}"
    fg = resolve_color(color, NORD, CARD)
    backdrop = effective_bg(RULES, fchain, NORD, CARD)
    bg_decl = props.get("background")
    bg = resolve_color(bg_decl, NORD, backdrop) if bg_decl else backdrop
    ratio = contrast_ratio(fg, bg)
    assert ratio >= AA_TEXT, f"{name}: {ratio:.2f}:1 ({fg} on {bg}) < {AA_TEXT}:1"


@pytest.mark.parametrize(
    "name,chain",
    [
        ("stat ok left border", [["nc-stat", "nc-stat-ok"]]),
        ("stat warn left border", [["nc-stat", "nc-stat-warn"]]),
    ],
)
def test_status_signal_non_text_contrast(name: str, chain: list[list[str]]) -> None:
    """The colored left border carrying stat status must reach 3:1 vs the stat bg."""
    fchain = [frozenset(c) for c in chain]
    props = cascade(RULES, fchain)
    border = props.get("border-left") or props.get("border") or ""
    assert "var(" in border or border.startswith("#"), f"{name}: no border color in {border!r}"
    color_token = border[border.index("var("):] if "var(" in border else border.split()[-1]
    fg = resolve_color(color_token, NORD, CARD)
    bg = effective_bg(RULES, fchain, NORD, CARD)
    ratio = contrast_ratio(fg, bg)
    assert ratio >= AA_NON_TEXT, f"{name}: {ratio:.2f}:1 ({fg} on {bg}) < {AA_NON_TEXT}:1"


def test_gate_destructive_tint_is_pinned() -> None:
    """The destructive/mixed badge override must exist and stay at the 25% tint.

    Without the override the host's solid-destructive badge shows through
    (3.55:1 under nord); this pins the color-mix pill that fixes it.
    """
    chain = [frozenset({"nc-list"}), frozenset({"nc-row"}), frozenset({"nc-gatebadge", "nc-gate-destructive"})]
    props = cascade(RULES, chain)
    assert "background" in props and "color-mix" in props["background"]
    bg = resolve_color(props["background"], NORD, CARD)
    expected = srgb_mix(NORD["--color-destructive"], NORD["--color-card"], 25).lower()
    assert bg == expected, f"destructive badge bg drifted: {bg} != {expected}"


def test_stat_value_never_carries_status_color() -> None:
    """The primary number must resolve to foreground, not success/warning.

    Guards the 4.23:1 regression: if a status color lands on .nc-stat-value
    again, the parametrized ratio test above fails as well, this pins the cause.
    """
    for mod in ("nc-stat-ok", "nc-stat-warn"):
        chain = [frozenset({"nc-stat", mod}), frozenset({"nc-stat-value"})]
        color = resolve_color(cascade(RULES, chain)["color"], NORD, CARD)
        assert color == NORD["--color-foreground"].lower(), f"{mod} stat value color: {color}"


def test_font_size_floor() -> None:
    """No text in the tab may drop below 0.75 rem (the host's readable-text minimum)."""
    css = CSS_PATH.read_text(encoding="utf-8")
    assert "0.6875rem" not in css
    floor_selectors = [
        [["nc-stat-label"]],
        [["nc-cols"]],
        [["nc-group-count"]],
        [["nc-saving"]],
        [["nc-param-type"]],
        [["nc-param-default"]],
        [["nc-row"], ["nc-gatebadge"]],
        [["nc-nav"], ["nc-navrow"], ["nc-search"]],
        [["nc-nav"], ["nc-navrow"], ["nc-filterlabel"]],
        [["nc-nav"], ["nc-chip"]],
        [["nc-nav"], ["nc-chip", "nc-chip-on"]],
        [["nc-listbar"], ["nc-count"]],
        [["nc-listbar"], ["nc-action"]],
    ]
    for chain in floor_selectors:
        fchain = [frozenset(c) for c in chain]
        font_size = cascade(RULES, fchain).get("font-size")
        assert font_size, f"no font-size on {chain[-1]}"
        assert _rem(font_size) >= SIZE_FLOOR_REM, f"{chain[-1]}: {font_size} < {SIZE_FLOOR_REM}rem"
