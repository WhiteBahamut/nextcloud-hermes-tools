"""Mock-host theme support: load Hermes dashboard-theme YAML files (mock/*.yaml)
and compile them to the CSS the mock page applies on top of its default tokens.

Stdlib only (the mock server is stdlib-only, no PyYAML). The parser handles the
subset of YAML the dashboard-theme format uses: nested block maps by indentation,
`key: {flow: map}` inline maps, quoted scalars, numbers, booleans, and `key: |`
literal block scalars (used by customCSS). Comments (# ...) are stripped outside
quotes, so hex colors like "#2E3440" survive.

The compiler mirrors the host's theme model (Hermes web_server bootstrap +
web/src/themes/context.tsx, verified against the pinned host source):
  palette.background/midground/foreground -> layer vars --background / --midground /
      --foreground (alpha applied) plus bootstrap --background-base / --midground-base
      (hex only, alpha dropped); the shadcn base tokens are derived from the layers:
      --color-background: var(--background), --color-foreground: var(--foreground).
      NOTE: that derivation routes --color-foreground through the foreground layer,
      so a theme with foreground alpha 0 (like nord) must pin --color-foreground in
      customCSS with !important — otherwise all var(--color-foreground, …) text is
      invisible on the live host (this exact bug shipped in nord.yaml once).
  colorOverrides.<camelKey>      -> --color-<kebab> AND --<kebab> (shadcn fallback)
  componentStyles.<bucket>.<camelProp> -> --component-<bucket>-<kebab>
  typography.fontSans/fontMono/baseSize/lineHeight/letterSpacing -> body + html rules
      (fontMono also lands on --font-mono / --theme-font-mono, which the tab reads)
  typography.fontUrl             -> reported to the client, injected as <link>
  layout.radius                  -> --radius + --radius-lg/md/sm cascade
  layout.density                 -> --spacing-mul (compact .85 / comfortable 1 / spacious 1.2)
  customCSS                      -> appended raw (host cap: 32 KiB, enforced here)

Neutral tokens a theme leaves unpinned are derived from the palette triplet with
color-mix() approximations (marked in the emitted CSS) — the host derives them in
its own DS cascade; themes that care (like nord.yaml, which pins every supported
key) are unaffected.
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_THEME_NAME = "__default__"
DEFAULT_THEME_LABEL = "Mock light (zinc) — built-in"
CUSTOM_CSS_CAP = 32 * 1024  # host cap per theme

# colorOverrides keys the host supports (dashboard-themes docs); each maps 1:1 to
# --color-<kebab>. Used to validate theme files and to derive the missing neutrals.
SUPPORTED_OVERRIDES = [
    "card", "cardForeground", "popover", "popoverForeground", "primary",
    "primaryForeground", "secondary", "secondaryForeground", "muted",
    "mutedForeground", "accent", "accentForeground", "destructive",
    "destructiveForeground", "success", "warning", "border", "input", "ring",
]

DENSITY_MUL = {"compact": 0.85, "comfortable": 1.0, "spacious": 1.2}


# ---------- tiny YAML-subset parser ----------

def _strip_comment(line: str) -> str:
    """Drop a trailing # comment, respecting single/double quotes."""
    out: list[str] = []
    quote: str | None = None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(text: str):
    """Parse a YAML scalar: quoted string, bool, int, float, or bare string."""
    s = text.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if s == "true":
        return True
    if s == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _split_flow(text: str) -> list[str]:
    """Split on top-level commas, respecting quotes, (), {} and []."""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    cur = ""
    for ch in text:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur += ch
            continue
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def _parse_flow(text: str) -> dict:
    """Parse an inline `{key: value, ...}` map."""
    s = text.strip()
    if not (s.startswith("{") and s.endswith("}")):
        raise ValueError(f"not a flow map: {text!r}")
    out: dict = {}
    for part in _split_flow(s[1:-1]):
        key, _, value = part.partition(":")
        out[key.strip()] = _scalar(value)
    return out


def parse_theme_yaml(text: str) -> dict:
    """Parse the YAML subset used by dashboard-theme files into nested dicts."""
    raw_lines = text.splitlines()
    lines: list[tuple[int, str] | None] = []
    for raw in raw_lines:
        stripped = _strip_comment(raw)
        if stripped.strip() == "":
            lines.append(None)
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip()))

    def parse_block(i: int, indent: int) -> tuple[dict, int]:
        out: dict = {}
        while i < len(lines):
            item = lines[i]
            if item is None:
                i += 1
                continue
            ind, content = item
            if ind < indent:
                break
            if ind > indent:
                raise ValueError(f"unexpected indent at line: {content!r}")
            key, sep, rest = content.partition(":")
            if not sep:
                raise ValueError(f"not a key: line: {content!r}")
            key = key.strip()
            rest = rest.strip()
            if rest == "":
                j = i + 1
                while j < len(lines) and lines[j] is None:
                    j += 1
                if j < len(lines) and lines[j][0] > indent:  # type: ignore[union-attr]
                    value, j = parse_block(j, lines[j][0])  # type: ignore[arg-type]
                    out[key] = value
                    i = j
                else:
                    out[key] = None
                    i = j
            elif rest in ("|", "|-", "|+"):
                # Literal block scalar: content is RAW (no comment stripping —
                # `#2E3440` inside customCSS is a color, not a YAML comment).
                j = i + 1
                block: list[str] = []
                block_indent: int | None = None
                while j < len(raw_lines):
                    raw_line = raw_lines[j]
                    if raw_line.strip() == "":
                        block.append("")
                        j += 1
                        continue
                    ind2 = len(raw_line) - len(raw_line.lstrip(" "))
                    if ind2 <= indent:
                        break
                    if block_indent is None:
                        block_indent = ind2
                    block.append(raw_line[block_indent:])
                    j += 1
                while block and block[-1] == "":
                    block.pop()
                out[key] = "\n".join(block) + "\n"
                i = j
            elif rest.startswith("{"):
                out[key] = _parse_flow(rest)
                i += 1
            else:
                out[key] = _scalar(rest)
                i += 1
        return out, i

    result, _ = parse_block(0, 0)
    return result


# ---------- theme file discovery ----------

def _kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def _layer_css(value) -> str:
    """A palette layer ({hex, alpha} or bare string) as a CSS color (alpha applied)."""
    if isinstance(value, dict):
        hexv = str(value.get("hex", "#000000"))
        alpha = value.get("alpha", 1)
        alpha = 1 if alpha is None else float(alpha)
        if alpha >= 1:
            return hexv
        return f"rgba({_layer_rgb(hexv)}, {alpha})"
    return str(value)


def _layer_hex(value) -> str:
    """A palette layer as bare hex — alpha dropped, like the host's _layer_hex."""
    if isinstance(value, dict):
        return str(value.get("hex", "#000000"))
    return str(value)


def _layer_rgb(hexv: str) -> str:
    h = hexv.lstrip("#")
    return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"


def list_themes(mock_root: Path) -> list[dict]:
    """Theme picker entries: the built-in mock theme first, then every mock/*.yaml."""
    themes: list[dict] = [{
        "name": DEFAULT_THEME_NAME,
        "label": DEFAULT_THEME_LABEL,
        "description": "The inline light zinc tokens in mock/index.html (the original mock look).",
        "builtin": True,
        "fontUrl": None,
    }]
    for path in sorted(mock_root.glob("*.yaml")):
        entry = {"name": path.stem, "label": path.stem, "description": None, "builtin": False, "fontUrl": None}
        try:
            theme = parse_theme_yaml(path.read_text(encoding="utf-8"))
            entry["name"] = str(theme.get("name") or path.stem)
            entry["label"] = str(theme.get("label") or entry["name"])
            entry["description"] = theme.get("description")
            font_url = (theme.get("typography") or {}).get("fontUrl")
            entry["fontUrl"] = str(font_url) if font_url else None
        except (OSError, ValueError) as exc:
            entry["label"] = f"{path.stem} (parse error)"
            entry["description"] = f"{path.name}: {exc}"
        themes.append(entry)
    return themes


def theme_css(mock_root: Path, name: str) -> str:
    """Compiled CSS for a theme name; "" for the built-in default (client removes overrides)."""
    if name == DEFAULT_THEME_NAME:
        return "/* built-in mock theme: no overrides, mock/index.html tokens apply */\n"
    candidate = (mock_root / f"{name}.yaml").resolve()
    if mock_root.resolve() not in candidate.parents or not candidate.is_file():
        raise ValueError(f"unknown mock theme: {name!r}")
    theme = parse_theme_yaml(candidate.read_text(encoding="utf-8"))
    return compile_theme_css(theme)


# ---------- theme dict -> CSS ----------

def _derived_neutrals(pal: dict) -> dict[str, str]:
    """Approximate host DS derivations for colorOverride keys a theme leaves unset.

    Only neutrals are derived; status colors (destructive/success/warning) have no
    sane derivation from the triplet, so they are left to the page's own fallbacks
    (mock/index.html) — themes that care pin them, like nord.yaml does.
    """
    bg = _layer_css(pal.get("background", "#000000"))
    mid = _layer_css(pal.get("midground", "#ffffff"))
    mix = lambda pct: f"color-mix(in srgb, {mid} {pct}%, {bg})"  # noqa: E731
    return {
        "card": mix(7), "cardForeground": mid,
        "popover": mix(7), "popoverForeground": mid,
        "muted": mix(12), "mutedForeground": mix(70),
        "secondary": mix(18), "secondaryForeground": mid,
        "accent": mix(40), "accentForeground": bg,
        "primary": mid, "primaryForeground": bg,
        "border": mix(22), "input": mix(14), "ring": mid,
    }


def compile_theme_css(theme: dict) -> str:
    """Compile a parsed theme dict to a CSS stylesheet the mock injects on :root."""
    root: list[str] = []
    pal = theme.get("palette") or {}
    bg = _layer_css(pal.get("background", "#000000"))
    mid = _layer_css(pal.get("midground", "#ffffff"))
    fg = _layer_css(pal.get("foreground", {"hex": "#ffffff", "alpha": 0}))
    bg_hex = _layer_hex(pal.get("background", "#000000"))
    mid_hex = _layer_hex(pal.get("midground", "#ffffff"))
    # Host-faithful layer vars (web_server bootstrap + ThemeProvider.layerVars):
    # the -base vars carry hex only (alpha dropped, like the host's _layer_hex),
    # the layer vars carry alpha, and the shadcn base tokens are DERIVED from the
    # layers — notably --color-foreground resolves through the foreground layer.
    # That is exactly the live-host behavior that made nord's alpha-0 foreground
    # layer blank all var(--color-foreground, …) text; themes compensate in
    # customCSS with !important pins (see mock/nord.yaml).
    root.append(f"--background-base: {bg_hex}; --midground-base: {mid_hex};")
    root.append(f"--background: {bg}; --midground: {mid}; --foreground: {fg};")
    root.append("--color-background: var(--background);")
    root.append("--color-foreground: var(--foreground);")
    if pal.get("warmGlow") is not None:
        root.append(f"--mock-warm-glow: {pal['warmGlow']};")
    if pal.get("noiseOpacity") is not None:
        root.append(f"--mock-noise-opacity: {pal['noiseOpacity']};")

    overrides = theme.get("colorOverrides") or {}
    unknown = sorted(set(overrides) - set(SUPPORTED_OVERRIDES))
    if unknown:
        raise ValueError(f"unsupported colorOverrides keys: {', '.join(unknown)}")
    derived = _derived_neutrals(pal)
    for key in SUPPORTED_OVERRIDES:
        value = overrides.get(key, derived.get(key))
        if value is None:
            continue
        keb = _kebab(key)
        root.append(f"--color-{keb}: {value}; --{keb}: {value};")

    for bucket, props in (theme.get("componentStyles") or {}).items():
        for key, value in (props or {}).items():
            root.append(f"--component-{_kebab(str(bucket))}-{_kebab(str(key))}: {value};")

    layout = theme.get("layout") or {}
    if layout.get("radius"):
        r = layout["radius"]
        root.append(f"--radius: {r}; --radius-lg: {r}; --radius-md: {r}; --radius-sm: min(0.25rem, {r});")
    if layout.get("density"):
        root.append(f"--spacing-mul: {DENSITY_MUL.get(str(layout['density']), 1.0)};")

    typo = theme.get("typography") or {}
    if typo.get("fontSans"):
        root.append(f"--font-sans: {typo['fontSans']};")
    if typo.get("fontMono"):
        root.append(f"--font-mono: {typo['fontMono']}; --theme-font-mono: {typo['fontMono']};")

    parts = [":root {", "\n".join(f"  {line}" for line in root), "}"]

    body: list[str] = []
    if typo.get("fontSans"):
        body.append(f"font-family: {typo['fontSans']};")
    if typo.get("baseSize"):
        parts.append(f"html {{ font-size: {typo['baseSize']}; }}")
        body.append("font-size: 1rem; /* theme baseSize drives the rem scale */")
    if typo.get("lineHeight"):
        body.append(f"line-height: {typo['lineHeight']};")
    if typo.get("letterSpacing"):
        body.append(f"letter-spacing: {typo['letterSpacing']};")
    if body:
        parts.append("body { " + " ".join(body) + " }")

    custom = theme.get("customCSS")
    if custom:
        if len(custom) > CUSTOM_CSS_CAP:
            raise ValueError(f"customCSS exceeds {CUSTOM_CSS_CAP} bytes (host cap)")
        parts.append("/* ---- customCSS (raw, from theme) ---- */")
        parts.append(str(custom))
    return "\n".join(parts) + "\n"
