"""Theme — spec design tokens turned into the colors, fonts and shared CSS of every board.

All boards read colors from here, never from literals, so a new app gets its own
palette from `app.spec.json -> design.tokens` without touching the generators.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

from .. import spec as spec_mod

W, H = 390, 844  # iPhone board size (points)

# Series colors for charts/macros when the spec does not define `tokens.series`.
DEFAULT_SERIES = ["#F5B83D", "#9B7BFF", "#2F80ED", "#FF8E7A"]

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(a: str, b: str, t: float) -> str:
    """Linear mix of two #RRGGBB colors (t=0 → a, t=1 → b)."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return "#%02X%02X%02X" % (round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t))


def rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha:g})"


@dataclass
class Theme:
    name: str
    display_name: str
    mascot_name: str | None
    tokens: dict[str, str]
    display_font: str
    body_font: str
    series: list[str] = field(default_factory=lambda: list(DEFAULT_SERIES))

    # --- derived colors (kept here so every generator agrees) ---
    @property
    def bg(self) -> str: return self.tokens["background"]
    @property
    def ink(self) -> str: return self.tokens["ink"]
    @property
    def muted(self) -> str: return self.tokens["muted"]
    @property
    def line(self) -> str: return self.tokens["line"]
    @property
    def accent(self) -> str: return self.tokens["accent"]
    @property
    def accent_text(self) -> str: return self.tokens["accent_text"]
    @property
    def selected(self) -> str: return self.tokens["selected_fill"]
    @property
    def cta(self) -> str: return self.tokens["cta"]
    @property
    def cta_disabled(self) -> str: return self.tokens["cta_disabled"]
    @property
    def success(self) -> str: return self.tokens["success"]
    @property
    def surface(self) -> str: return self.tokens.get("surface", "#FFFFFF")
    @property
    def track(self) -> str: return mix(self.line, self.muted, 0.08)
    @property
    def soft(self) -> str: return mix(self.muted, self.bg, 0.3)
    @property
    def faint(self) -> str: return mix(self.line, self.muted, 0.3)
    @property
    def icon_bg(self) -> str: return mix(self.selected, self.surface, 0.45)
    @property
    def success_fill(self) -> str: return mix(self.success, self.surface, 0.84)
    @property
    def success_text(self) -> str: return mix(self.success, self.ink, 0.3)
    @property
    def glow(self) -> str: return mix(self.accent, self.bg, 0.72)
    @property
    def shadow(self) -> str: return rgba(self.ink, 0.08)
    @property
    def cta_shadow(self) -> str: return rgba(self.cta, 0.32)

    @property
    def display_css(self) -> str:
        return f"'{self.display_font}', Georgia, serif"

    @property
    def body_css(self) -> str:
        return f"'{self.body_font}', system-ui, -apple-system, sans-serif"

    def fonts_link(self) -> str:
        fams = []
        for fam, weights in ((self.display_font, "600;700;800"), (self.body_font, "400;500;600;700;800")):
            fams.append("family=" + fam.replace(" ", "+") + ":wght@" + weights)
        url = "https://fonts.googleapis.com/css2?" + "&amp;".join(fams) + "&amp;display=swap"
        return ('<link rel="preconnect" href="https://fonts.googleapis.com">'
                f'<link href="{url}" rel="stylesheet">')

    def text(self, s: str | None) -> str:
        """Escape user copy, expand {app}/{mascot} and turn **x** into an accent highlight."""
        if not s:
            return ""
        out = html.escape(s, quote=False).replace("'", "&#39;")
        out = out.replace("{app}", html.escape(self.display_name)).replace(
            "{mascot}", html.escape(self.mascot_name or self.display_name))
        return re.sub(r"\*\*(.+?)\*\*", lambda m: f'<span style="color: {self.accent_text}">{m.group(1)}</span>', out)

    def base_css(self) -> str:
        """Shared stylesheet: every board gets the same @keyframes vocabulary."""
        t = self
        return f"""
body{{margin:0;font-family:{t.body_css};color:{t.ink};background:{t.bg};-webkit-font-smoothing:antialiased}}
a{{color:{t.ink};text-decoration:none}}a:hover{{color:{t.accent_text}}}
button{{font-family:inherit;color:inherit}}
.snap{{scrollbar-width:none}}.snap::-webkit-scrollbar{{display:none}}
@keyframes rise{{from{{opacity:0;transform:translateY(16px)}}}}
@keyframes pop{{0%{{opacity:0;transform:scale(.55)}}70%{{opacity:1;transform:scale(1.07)}}100%{{transform:scale(1)}}}}
@keyframes bob{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-8px)}}}}
@keyframes draw{{from{{stroke-dashoffset:700}}}}
@keyframes ring{{from{{stroke-dashoffset:var(--c)}}}}
@keyframes growY{{from{{transform:scaleY(0)}}}}
@keyframes barIn{{from{{transform:scaleX(var(--from))}}}}
@keyframes scan{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(178px)}}}}
@keyframes pulse{{0%{{transform:scale(.85);opacity:.5}}100%{{transform:scale(1.6);opacity:0}}}}
@keyframes fall{{0%{{transform:translateY(-60px) rotate(0deg);opacity:0}}8%{{opacity:1}}100%{{transform:translateY(900px) rotate(620deg);opacity:0}}}}
@keyframes fadein{{from{{opacity:0}}}}
@keyframes wave{{0%,100%{{transform:rotate(0deg)}}50%{{transform:rotate(-22deg)}}}}
@keyframes blink{{0%,90%,93.5%,100%{{opacity:0}}91%,92.5%{{opacity:1}}}}
@keyframes dot{{0%,100%{{opacity:.25}}50%{{opacity:1}}}}
@keyframes float{{0%{{transform:translateY(0);opacity:0}}20%{{opacity:1}}100%{{transform:translateY(-120px);opacity:0}}}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
@keyframes shine{{0%,55%{{transform:translateX(-160%) skewX(-20deg)}}100%{{transform:translateX(420%) skewX(-20deg)}}}}
input[type=range].rng{{-webkit-appearance:none;appearance:none;width:100%;height:10px;border-radius:5px;background:linear-gradient(90deg,{t.accent} var(--p),{t.line} var(--p));outline:none;margin:0}}
input[type=range].rng::-webkit-slider-thumb{{-webkit-appearance:none;width:34px;height:34px;border-radius:50%;background:{t.surface};border:4px solid {t.accent};box-shadow:0 6px 16px {rgba(t.accent, .35)};cursor:grab}}
input[type=range].rng::-moz-range-thumb{{width:26px;height:26px;border-radius:50%;background:{t.surface};border:4px solid {t.accent};box-shadow:0 6px 16px {rgba(t.accent, .35)};cursor:grab}}
@media (prefers-reduced-motion: reduce){{*{{animation:none!important;transition:none!important}}}}
"""


def from_spec(spec: dict[str, Any]) -> Theme:
    design = spec_mod._merge(spec_mod.DEFAULTS["design"], spec.get("design") or {})
    tokens = dict(spec_mod.DEFAULTS["design"]["tokens"])
    tokens.update(design.get("tokens") or {})
    bad = [k for k, v in tokens.items() if isinstance(v, str) and not _HEX.match(v)]
    if bad:
        raise ValueError(f"design.tokens must be #RRGGBB: {', '.join(sorted(bad))}")
    series = tokens.pop("series", None) if isinstance(tokens.get("series"), list) else None
    base = spec_mod.DEFAULTS["design"]["tokens"]
    # A re-branded CTA keeps a matching disabled state unless the spec sets one explicitly.
    if tokens["cta"] != base["cta"] and tokens["cta_disabled"] == base["cta_disabled"]:
        tokens["cta_disabled"] = mix(tokens["cta"], tokens["background"], 0.62)
    mascot = design.get("mascot") or {}
    fonts = design.get("fonts") or {}
    return Theme(
        name=spec.get("name", "App"),
        display_name=spec.get("display_name") or spec.get("name", "App"),
        mascot_name=mascot.get("name"),
        tokens=tokens,
        display_font=fonts.get("display", "Bricolage Grotesque"),
        body_font=fonts.get("body", "Figtree"),
        series=series or [tokens["accent"]] + DEFAULT_SERIES,
    )
