"""Claude Design component (`.dc.html`) primitives shared by every generator.

A board is one HTML file: `<x-dc>` markup with `{{binding}}` holes, a `<helmet>` with the
fonts + shared CSS, and a `DCLogic` class whose `renderVals()` feeds the bindings. The
runtime (`support.js`) is written into the project by `create_support_js`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .theme import H, W, Theme, rgba

ICONS = {
    "back": '<polyline points="15 18 9 12 15 6"></polyline>',
    "check": '<polyline points="5 12.5 10 17 19 7"></polyline>',
    "close": '<line x1="6" y1="6" x2="18" y2="18"></line><line x1="18" y1="6" x2="6" y2="18"></line>',
    "chevron": '<polyline points="9 6 15 12 9 18"></polyline>',
    "male": '<circle cx="10" cy="14" r="6"></circle><path d="M14.5 9.5L20 4"></path><path d="M15 4h5v5"></path>',
    "female": '<circle cx="12" cy="9" r="6"></circle><path d="M12 15v7"></path><path d="M9 19h6"></path>',
    "other": '<path d="M12 3v18"></path><path d="M4.2 7.5l15.6 9"></path><path d="M19.8 7.5l-15.6 9"></path>',
    "w1": '<circle cx="12" cy="12" r="2.6" fill="currentColor" stroke="none"></circle>',
    "w2": '<circle cx="12" cy="7" r="2.4" fill="currentColor" stroke="none"></circle><circle cx="7" cy="16" r="2.4" fill="currentColor" stroke="none"></circle><circle cx="17" cy="16" r="2.4" fill="currentColor" stroke="none"></circle>',
    "w3": '<circle cx="6" cy="8" r="2.1" fill="currentColor" stroke="none"></circle><circle cx="12" cy="8" r="2.1" fill="currentColor" stroke="none"></circle><circle cx="18" cy="8" r="2.1" fill="currentColor" stroke="none"></circle><circle cx="6" cy="16" r="2.1" fill="currentColor" stroke="none"></circle><circle cx="12" cy="16" r="2.1" fill="currentColor" stroke="none"></circle><circle cx="18" cy="16" r="2.1" fill="currentColor" stroke="none"></circle>',
    "music": '<path d="M9 18V5l11-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="17" cy="16" r="3"></circle>',
    "camera": '<rect x="3" y="3" width="18" height="18" rx="5"></rect><circle cx="12" cy="12" r="4"></circle><circle cx="17.5" cy="6.5" r="0.8" fill="currentColor"></circle>',
    "play": '<rect x="2.5" y="5.5" width="19" height="13" rx="4"></rect><path d="M10 9.5v5l4.5-2.5z" fill="currentColor"></path>',
    "store": '<rect x="3" y="3" width="18" height="18" rx="5"></rect><path d="M9 16l3-8 3 8"></path><path d="M10 13.5h4"></path>',
    "search": '<circle cx="11" cy="11" r="7"></circle><line x1="20" y1="20" x2="16" y2="16"></line>',
    "users": '<circle cx="9" cy="8" r="3.5"></circle><path d="M2.5 20a6.5 6.5 0 0 1 13 0"></path><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"></path><path d="M18 14.2a6.5 6.5 0 0 1 3.5 5.8"></path>',
    "dots": '<circle cx="6" cy="12" r="1.2" fill="currentColor"></circle><circle cx="12" cy="12" r="1.2" fill="currentColor"></circle><circle cx="18" cy="12" r="1.2" fill="currentColor"></circle>',
    "down": '<polyline points="22 17 13.5 8.5 8.5 13.5 2 7"></polyline><polyline points="16 17 22 17 22 11"></polyline>',
    "up": '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline><polyline points="16 7 22 7 22 13"></polyline>',
    "equal": '<line x1="5" y1="9" x2="19" y2="9"></line><line x1="5" y1="15" x2="19" y2="15"></line>',
    "repeat": '<path d="M17 2l4 4-4 4"></path><path d="M3 11V9a3 3 0 0 1 3-3h15"></path><path d="M7 22l-4-4 4-4"></path><path d="M21 13v2a3 3 0 0 1-3 3H3"></path>',
    "clock": '<circle cx="12" cy="12" r="9"></circle><polyline points="12 7 12 12 15.5 14"></polyline>',
    "bulb": '<path d="M9 18h6"></path><path d="M10 21h4"></path><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"></path>',
    "heart": '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"></path>',
    "bolt": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"></path>',
    "target": '<circle cx="12" cy="12" r="9"></circle><circle cx="12" cy="12" r="5"></circle><circle cx="12" cy="12" r="1" fill="currentColor"></circle>',
    "smile": '<circle cx="12" cy="12" r="9"></circle><path d="M8.5 14a4 4 0 0 0 7 0"></path><circle cx="9" cy="9.5" r="0.9" fill="currentColor"></circle><circle cx="15" cy="9.5" r="0.9" fill="currentColor"></circle>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"></path><polyline points="8.5 12 11 14.5 15.5 9.5"></polyline>',
    "lock": '<rect x="4" y="10" width="16" height="11" rx="3"></rect><path d="M8 10V7a4 4 0 0 1 8 0v3"></path>',
    "flame": '<path d="M12 22c4 0 7-3 7-7 0-4-3-6-4-10-2 2-3 4-3 6-1-1-2-2-2-4-2 2-5 5-5 8 0 4 3 7 7 7z"></path>',
    "scale": '<rect x="3" y="4" width="18" height="16" rx="4"></rect><path d="M9 9a3 3 0 0 1 6 0"></path><line x1="12" y1="9" x2="13.5" y2="7"></line>',
    "pencil": '<path d="M4 20h4L19 9l-4-4L4 16z"></path>',
    "gift": '<rect x="3" y="9" width="18" height="12" rx="2"></rect><path d="M12 9v12"></path><path d="M2 9h20"></path>',
    "sparkle": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"></path>',
    "camera2": '<path d="M4 8h3l2-3h6l2 3h3v11H4z"></path><circle cx="12" cy="13" r="3.5"></circle>',
    "chart": '<path d="M4 20V10"></path><path d="M10 20V4"></path><path d="M16 20v-7"></path><path d="M22 20H2"></path>',
    "globe": '<circle cx="12" cy="12" r="9"></circle><path d="M3 12h18"></path><path d="M12 3c3 3.5 3 14.5 0 18"></path><path d="M12 3c-3 3.5-3 14.5 0 18"></path>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1.2 0 2-.8 2-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-1 .8-1.8 1.8-1.8H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z"></path><circle cx="7.5" cy="11" r="1.2" fill="currentColor"></circle><circle cx="10" cy="7.5" r="1.2" fill="currentColor"></circle><circle cx="14.5" cy="7.5" r="1.2" fill="currentColor"></circle>',
    "sun": '<circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"></path>',
    "burger": '<path d="M4 11h16"></path><path d="M5 11a7 7 0 0 1 14 0"></path><path d="M4 15h16"></path><path d="M5 15v1a3 3 0 0 0 3 3h8a3 3 0 0 0 3-3v-1"></path>',
    "coffee": '<path d="M4 9h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z"></path><path d="M17 11h1.5a2.5 2.5 0 0 1 0 5H17"></path><path d="M8 3v3M12 3v3"></path>',
    "pizza": '<path d="M12 3l9 16H3z"></path><circle cx="11" cy="12" r="1.2" fill="currentColor"></circle><circle cx="14" cy="15" r="1.2" fill="currentColor"></circle>',
    "sprout": '<path d="M12 21v-8"></path><path d="M12 13c0-4-3-6-7-6 0 4 3 6 7 6z"></path><path d="M12 11c0-4 3-6 7-6 0 4-3 6-7 6z"></path>',
    "leaf": '<path d="M5 19c0-9 6-14 15-14 0 9-5 15-14 15"></path><path d="M5 19l7-7"></path>',
    "home": '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"></path>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"></rect><path d="M3 10h18"></path><path d="M8 3v4M16 3v4"></path>',
    "settings": '<circle cx="12" cy="12" r="3"></circle><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"></path>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"></rect><path d="M5 11a7 7 0 0 0 14 0"></path><path d="M12 18v3"></path>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="3"></rect><circle cx="9" cy="10" r="2"></circle><path d="M21 16l-5-5-8 9"></path>',
}


def icon(name: str, size: int = 22, color: str = "currentColor", sw: float = 1.9, extra: str = "") -> str:
    path = ICONS.get(name, ICONS["sparkle"])
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{sw}" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="color: {color if not color.startswith("{{") else "inherit"}; {extra}">{path}</svg>')


@dataclass
class Ctx:
    """Everything a board renderer needs besides its own screen entry."""
    theme: Theme
    spec: dict[str, Any]
    mascot: dict[str, str] = field(default_factory=dict)   # state -> project-relative png
    blink: dict[str, str] = field(default_factory=dict)    # state -> project-relative closed-eye png
    app_icon: str | None = None                            # project-relative png
    files: dict[str, str] = field(default_factory=dict)    # screen id -> board file name
    first_main: str = "#"
    doc: dict[str, Any] = field(default_factory=dict)      # the screens.json document

    def href(self, screen_id: str | None) -> str:
        return self.files.get(screen_id or "", "#")


def page(t: Theme, title: str, body: str, js: str = "renderVals() { return {}; }",
         props: dict | None = None, w: int = W, h: int = H, css: str = "", frame: bool = True) -> str:
    data_props = json.dumps(dict(props or {}, **{"$preview": {"width": w, "height": h}})).replace("'", "&#39;")
    inner = (f'<div style="width: {w}px; height: {h}px; box-sizing: border-box; display: flex; flex-direction: column; '
             f'background: {t.bg}; position: relative; overflow: hidden">\n{body}\n</div>') if frame else body
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            f"<title>{title}</title>\n<script src=\"./support.js\"></script>\n</head>\n<body>\n<x-dc>\n<helmet>\n"
            f"{t.fonts_link()}\n<style>{t.base_css()}{css}</style>\n</helmet>\n{inner}\n</x-dc>\n"
            f"<script type=\"text/x-dc\" data-dc-script data-props='{data_props}'>\n"
            f"class Component extends DCLogic {{\n{js}\n}}\n</script>\n</body>\n</html>\n")


# ---------- mascot ----------

def mascot_svg(t: Theme, size: int, anim: str = "bob 2.6s ease-in-out infinite", delay: str = "0s") -> str:
    """Token-tinted placeholder character, used until approved pose PNGs exist."""
    h = int(size * 1.2)
    body, belly = t.accent, t.selected
    return (f'<svg width="{size}" height="{h}" viewBox="0 0 100 120" aria-hidden="true" data-placeholder="mascot" '
            f'style="overflow: visible; animation: {anim}; animation-delay: {delay}">'
            f'<ellipse cx="50" cy="117" rx="26" ry="3.5" fill="{t.ink}" opacity=".08"></ellipse>'
            f'<path d="M50 6 C30 6 22 30 20 48 C16 70 10 82 14 96 C19 112 34 118 50 118 C66 118 81 112 86 96 C90 82 84 70 80 48 C78 30 70 6 50 6Z" fill="{body}"></path>'
            f'<path d="M50 14 C35 14 29 33 27.5 50 C24.5 70 19.5 82 22.5 94 C26.5 107 38 111 50 111 C62 111 73.5 107 77.5 94 C80.5 82 75.5 70 72.5 50 C71 33 65 14 50 14Z" fill="{belly}"></path>'
            f'<circle cx="40" cy="55" r="3.8" fill="{t.ink}"></circle><circle cx="60" cy="55" r="3.8" fill="{t.ink}"></circle>'
            f'<circle cx="41.3" cy="53.8" r="1.2" fill="#FFFFFF"></circle><circle cx="61.3" cy="53.8" r="1.2" fill="#FFFFFF"></circle>'
            f'<ellipse cx="33" cy="63" rx="4.5" ry="2.6" fill="#FF8E7A" opacity=".75"></ellipse><ellipse cx="67" cy="63" rx="4.5" ry="2.6" fill="#FF8E7A" opacity=".75"></ellipse>'
            f'<path d="M44 63 Q50 69.5 56 63" stroke="{t.ink}" stroke-width="2.6" stroke-linecap="round" fill="none"></path></svg>')


def mascot(ctx: Ctx, state: str, size: int, anim: str = "bob 2.6s ease-in-out infinite", delay: str = "0s", extra: str = "") -> str:
    """The approved pose PNG for `state` (blink layered on top), or the placeholder SVG."""
    src = ctx.mascot.get(state) or ctx.mascot.get("idle")
    if not src:
        return mascot_svg(ctx.theme, size, anim, delay)
    blink = ctx.blink.get(state) if state in ctx.mascot else ctx.blink.get("idle")
    img = (f'<img src="{src}" alt="" width="{size}" height="{size}" style="position: absolute; inset: 0; display: block; '
           f'width: {size}px; height: {size}px; object-fit: contain">')
    if blink:
        img += (f'<img src="{blink}" alt="" width="{size}" height="{size}" style="position: absolute; inset: 0; display: block; '
                f'width: {size}px; height: {size}px; object-fit: contain; opacity: 0; animation: blink 4.4s linear infinite">')
    return (f'<div data-mascot="{state}" style="position: relative; width: {size}px; height: {size}px; flex-shrink: 0; '
            f'animation: {anim}; animation-delay: {delay}; {extra}">{img}</div>')


def app_mark(ctx: Ctx, size: int = 36) -> str:
    t = ctx.theme
    if ctx.app_icon:
        return (f'<img src="{ctx.app_icon}" alt="" width="{size}" height="{size}" style="width: {size}px; height: {size}px; '
                f'border-radius: {round(size * 0.3)}px; display: block">')
    return (f'<span style="width: {size}px; height: {size}px; border-radius: {round(size * 0.3)}px; background: {t.accent}; '
            f'color: #FFFFFF; display: flex; align-items: center; justify-content: center; font-family: {t.display_css}; '
            f'font-weight: 800; font-size: {round(size * 0.5)}px">{t.text(t.display_name[:1])}</span>')


# ---------- layout pieces ----------

def l10n(key: str | None, part: str) -> str:
    return f' data-l10n="{key}.{part}"' if key else ""


def header(t: Theme, prev_href: str, frac: float, prev_frac: float) -> str:
    fr = (prev_frac / frac) if frac > 0 else 0.0
    return (f'<div style="display: flex; align-items: center; gap: 14px; padding: 56px 24px 0">'
            f'<a href="{prev_href}" aria-label="Back" style="width: 44px; height: 44px; border-radius: 22px; background: {t.surface}; '
            f'border: 1.5px solid {t.line}; display: flex; align-items: center; justify-content: center; flex-shrink: 0; box-sizing: border-box">'
            f'{icon("back", 20, t.ink, 2.2)}</a>'
            f'<div style="flex-grow: 1; height: 6px; border-radius: 3px; background: {t.line}; overflow: hidden">'
            f'<div style="--from: {fr:.3f}; width: {frac * 100:.1f}%; height: 100%; border-radius: 3px; background: {t.accent}; '
            f'transform-origin: left center; animation: barIn .8s cubic-bezier(.2,.8,.2,1) both"></div></div></div>')


def titles(t: Theme, title: str, sub: str | None = None, key: str | None = None, delay: float = 0.05, center: bool = False,
           size: int = 32) -> str:
    align = "align-items: center; text-align: center; " if center else ""
    s = (f'<div style="display: flex; flex-direction: column; gap: 10px; {align}animation: rise .55s cubic-bezier(.2,.8,.2,1) both; animation-delay: {delay:.2f}s">'
         f'<h1{l10n(key, "title")} style="margin: 0; font-family: {t.display_css}; font-size: {size}px; line-height: 1.08; font-weight: 800; '
         f'letter-spacing: -0.025em; text-wrap: balance">{t.text(title)}</h1>')
    if sub:
        s += (f'<p{l10n(key, "subtitle")} style="margin: 0; font-size: 16px; line-height: 1.45; color: {t.muted}; text-wrap: pretty">'
              f'{t.text(sub)}</p>')
    return s + "</div>"


def cta(t: Theme, href: str, label: str = "Continue", bg: str | None = None, extra: str = "", key: str | None = None) -> str:
    return (f'<div style="padding: 12px 24px 34px; display: flex; flex-direction: column; gap: 14px; align-items: stretch">'
            f'<a href="{href}"{l10n(key, "cta")} style="display: flex; align-items: center; justify-content: center; height: 58px; '
            f'border-radius: 29px; background: {bg or t.cta}; color: #FFFFFF; font-size: 19px; font-weight: 800; letter-spacing: 0.01em; '
            f'box-shadow: 0 12px 26px {t.cta_shadow}; transition: background .25s">{t.text(label)}</a>{extra}</div>')


def content(inner: str, gap: int = 28, pad: str = "28px 24px 0", justify: str = "flex-start") -> str:
    return (f'<div style="flex-grow: 1; display: flex; flex-direction: column; gap: {gap}px; padding: {pad}; '
            f'justify-content: {justify}; min-height: 0">{inner}</div>')


def card(t: Theme, inner: str, delay: float = 0.15, pad: str = "22px 20px 18px", gap: int = 14, radius: int = 28) -> str:
    return (f'<div style="background: {t.surface}; border-radius: {radius}px; padding: {pad}; box-shadow: 0 14px 36px {t.shadow}; '
            f'display: flex; flex-direction: column; gap: {gap}px; animation: rise .6s cubic-bezier(.2,.8,.2,1) both; '
            f'animation-delay: {delay:.2f}s">{inner}</div>')


def segmented(t: Theme, left: tuple[str, str], right: tuple[str, str], width: int | None = None, center: bool = False) -> str:
    """Two-state toggle (e.g. kg | lb). `left`/`right` = (label, lowercase binding id); handlers are to<Id>."""
    def btn(label: str, k: str) -> str:
        wcss = f"width: {width}px; " if width else "flex: 1; "
        return (f'<button type="button" onClick="{{{{to{k.capitalize()}}}}}" aria-pressed="{{{{{k}On}}}}" style="{wcss}height: 38px; border: none; '
                f'border-radius: 11px; font-size: 15px; font-weight: 800; cursor: pointer; background: {{{{{k}Bg}}}}; '
                f'color: {{{{{k}C}}}}; box-shadow: {{{{{k}Sh}}}}; transition: all .25s">{label}</button>')
    align = "align-self: center; " if center else ""
    return (f'<div style="{align}display: flex; padding: 4px; border-radius: 14px; background: {t.line}; gap: 4px; '
            f'animation: rise .5s both; animation-delay: .1s">{btn(*left)}{btn(*right)}</div>')


def segmented_js(t: Theme, a: str, b: str, state_key: str, b_value: str) -> str:
    """JS returning the bindings for `segmented` (a is on unless state == b_value)."""
    return (f'var _on = {{ bg: "{t.surface}", c: "{t.ink}", sh: "0 4px 12px {rgba(t.ink, .1)}" }}, '
            f'_off = {{ bg: "transparent", c: "{t.muted}", sh: "none" }};\n'
            f'  var _isB = st.{state_key} === "{b_value}", _a = _isB ? _off : _on, _b = _isB ? _on : _off;\n'
            f'  var seg = {{ {a}On: _isB ? "false" : "true", {b}On: _isB ? "true" : "false", '
            f'{a}Bg: _a.bg, {a}C: _a.c, {a}Sh: _a.sh, {b}Bg: _b.bg, {b}C: _b.c, {b}Sh: _b.sh }};')


def check_badge(t: Theme, k: str) -> str:
    return (f'<span style="width: 26px; height: 26px; border-radius: 13px; flex-shrink: 0; box-sizing: border-box; border: 2px solid {{{{{k}.cbd}}}}; '
            f'background: {{{{{k}.cb}}}}; display: flex; align-items: center; justify-content: center; transition: all .25s">'
            f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true" style="opacity: {{{{{k}.co}}}}; transform: scale({{{{{k}.co}}}}); '
            f'transition: all .3s cubic-bezier(.3,1.6,.5,1)">{ICONS["check"]}</svg></span>')


def sparkle_confetti(t: Theme, n: int = 18) -> str:
    cols = [t.accent] + t.series[1:4] + [t.success]
    return "".join(
        f'<div style="position: absolute; left: {(i * 47) % 380}px; top: 0; width: {8 if i % 3 else 10}px; height: {14 if i % 2 else 8}px; '
        f'border-radius: {"2px" if i % 3 else "50%"}; background: {cols[i % len(cols)]}; animation: fall {3.4 + (i % 4) * 0.5:.1f}s linear infinite; '
        f'animation-delay: {(i * 0.23) % 2.4:.2f}s; pointer-events: none"></div>' for i in range(n))


def pulse_rings(t: Theme, size: int = 180) -> str:
    return "".join(f'<div style="position: absolute; width: {size}px; height: {size}px; border-radius: 50%; border: 2px solid {t.accent}; '
                   f'animation: pulse 2.8s ease-out infinite; animation-delay: {d:.1f}s"></div>' for d in (0, 0.9, 1.8))


def floating_hearts(t: Theme) -> str:
    return "".join(f'<div style="position: absolute; left: {x}px; bottom: 40px; color: {t.accent}; animation: float 3.2s ease-out infinite; '
                   f'animation-delay: {d:.1f}s">{icon("heart", s, "currentColor", 2.2)}</div>'
                   for x, d, s in [(20, 0, 18), (150, 1.1, 14), (100, 2.1, 16)])
