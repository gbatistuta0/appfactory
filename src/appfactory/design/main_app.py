"""Main-app board renderers (canvas page "app") — same visual system as the onboarding."""

from __future__ import annotations

import json
from typing import Any, Callable

from .dc import Ctx, app_mark, content, cta, icon, l10n, mascot, page, titles
from .onboarding import b
from .theme import rgba

TAB_ICONS = {"home": "home", "progress": "chart", "history": "calendar", "settings": "settings", "list": "dots"}
WRAP = '<div style="position: absolute; inset: 0; display: flex; flex-direction: column; padding-bottom: 84px; box-sizing: border-box">'


def _tabs(ctx: Ctx) -> list[tuple[str, str, str]]:
    """(tab id, label, href) in screen order — one board per tab (the first screen that claims it)."""
    doc = ctx.doc
    seen, out = set(), []
    for s in doc.get("main", []):
        tab = s.get("tab")
        if tab and tab not in seen and s.get("kind") != "empty":
            seen.add(tab)
            out.append((tab, s.get("tab_label") or tab.capitalize(), ctx.href(s["id"])))
    for s in doc.get("main", []):  # a tab only claimed by the empty-state board still gets a link
        tab = s.get("tab")
        if tab and tab not in seen:
            seen.add(tab)
            out.append((tab, s.get("tab_label") or tab.capitalize(), ctx.href(s["id"])))
    return out


def _capture_href(ctx: Ctx) -> str | None:
    for s in ctx.doc.get("main", []):
        if s.get("kind") == "capture":
            return ctx.href(s["id"])
    return None


def tabbar(ctx: Ctx, active: str | None) -> str:
    t = ctx.theme
    tabs = _tabs(ctx)
    cap = _capture_href(ctx)
    cells: list[str] = []
    for tab, label, href in tabs:
        col = t.cta if tab == active else t.soft
        cells.append(f'<a href="{href}" style="display: flex; flex-direction: column; align-items: center; gap: 4px; padding-top: 10px; color: {col}; '
                     f'font-size: 11px; font-weight: 800">{icon(TAB_ICONS.get(tab, "dots"), 23, col, 2)}{t.text(label)}</a>')
    if cap:
        cells.insert(len(cells) // 2, _capture_cell(ctx, cap))
    return (f'<nav aria-label="Tabs" style="position: absolute; left: 0; right: 0; bottom: 0; height: 84px; background: {t.surface}; border-top: 1px solid {t.line}; '
            f'display: grid; grid-template-columns: repeat({max(1, len(cells))}, minmax(0, 1fr)); padding: 0 8px; box-sizing: border-box; z-index: 5">{"".join(cells)}</nav>')


def _capture_center_x(ctx: Ctx) -> float | None:
    """Horizontal center of the capture button in the tab bar (for the empty-state pulse)."""
    if not _capture_href(ctx):
        return None
    n = len(_tabs(ctx)) + 1
    idx = len(_tabs(ctx)) // 2
    cell = (390 - 16) / n
    return 8 + cell * (idx + 0.5)


def _capture_cell(ctx: Ctx, cap: str) -> str:
    t = ctx.theme
    return (f'<div style="display: flex; justify-content: center"><a href="{cap}" aria-label="Capture" style="width: 64px; height: 64px; margin-top: -26px; '
            f'border-radius: 32px; background: {t.cta}; display: flex; align-items: center; justify-content: center; box-shadow: 0 12px 26px {rgba(t.cta, .4)}; '
            f'border: 4px solid {t.bg}; box-sizing: border-box">{icon("camera2", 26, "#FFFFFF", 2.2)}</a></div>')


def topbar(ctx: Ctx, title: str, right: str = "", key: str | None = None) -> str:
    t = ctx.theme
    return (f'<div style="display: flex; align-items: center; justify-content: space-between; padding: 58px 22px 0">'
            f'<div style="display: flex; align-items: center; gap: 10px">{app_mark(ctx, 34)}'
            f'<span{l10n(key, "title")} style="font-family: {t.display_css}; font-size: 22px; font-weight: 800; letter-spacing: -0.02em">{t.text(title)}</span></div>{right}</div>')


def _ring(t, size: int, sw: int, frac: float, color: str, delay: float = 0.2, inner: str = "") -> str:
    r = (size - sw) / 2
    c = 2 * 3.14159 * r
    return (f'<div style="position: relative; width: {size}px; height: {size}px; flex-shrink: 0"><svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
            f'aria-hidden="true" style="transform: rotate(-90deg)"><circle cx="{size / 2}" cy="{size / 2}" r="{r:.1f}" fill="none" stroke="{t.line}" stroke-width="{sw}"></circle>'
            f'<circle cx="{size / 2}" cy="{size / 2}" r="{r:.1f}" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linecap="round" stroke-dasharray="{c:.1f}" '
            f'style="--c: {c:.1f}; stroke-dashoffset: {c * (1 - frac):.1f}; animation: ring 1.2s cubic-bezier(.3,.9,.3,1) both; animation-delay: {delay:.2f}s"></circle></svg>'
            f'<div style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center">{inner}</div></div>')


def _pill(ctx: Ctx, text: str, ic: str = "flame") -> str:
    t = ctx.theme
    return (f'<span style="display: flex; align-items: center; gap: 6px; padding: 7px 12px; border-radius: 999px; background: {t.surface}; '
            f'box-shadow: 0 4px 12px {rgba(t.ink, .06)}; font-size: 14px; font-weight: 800">{icon(ic, 16, t.cta, 2.2)}{t.text(text)}</span>')


_WEEK = (f'<div style="display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; padding: 16px 16px 0">'
         f'<sc-for list="{{{{days}}}}" as="d" hint-placeholder-count="7"><button type="button" onClick="{{{{d.pick}}}}" aria-pressed="{{{{d.on}}}}" '
         f'style="display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 8px 0; border: none; border-radius: 16px; background: {{{{d.bg}}}}; '
         f'cursor: pointer; transition: background .25s"><span style="font-size: 12px; font-weight: 800; color: {{{{d.lc}}}}">{{{{d.l}}}}</span>'
         f'<span style="width: 34px; height: 34px; border-radius: 17px; border: 3px solid {{{{d.ring}}}}; box-sizing: border-box; display: flex; align-items: center; '
         f'justify-content: center; font-size: 14px; font-weight: 800; color: {{{{d.nc}}}}">{{{{d.n}}}}</span></button></sc-for></div>')


def _week_js(ctx: Ctx, done: list[bool], today: int = 4) -> str:
    t = ctx.theme
    return f"""renderVals() {{
  var self = this;
  var labels = ["M","T","W","T","F","S","S"], done = {json.dumps(done)};
  var sel = (this.state && this.state.day != null) ? this.state.day : {today};
  var days = labels.map(function (l, i) {{
    var on = i === sel, future = i > {today};
    return {{ l: l, n: 21 + i, on: on ? "true" : "false", bg: on ? "{t.surface}" : "transparent", lc: on ? "{t.ink}" : "{t.soft}",
      nc: future ? "{t.faint}" : "{t.ink}", ring: done[i] ? "{t.cta}" : "{t.line}", pick: function () {{ self.setState({{ day: i }}); }} }};
  }});
  return {{ days: days }};
}}"""


def _summary(ctx: Ctx, s: dict[str, Any], delay: float = 0.15) -> str:
    t = ctx.theme
    sm = s.get("summary") or {"value": "0", "label": "", "frac": 0}
    return (f'<div style="display: flex; align-items: center; gap: 16px; padding: 20px; border-radius: 28px; background: {t.surface}; '
            f'box-shadow: 0 14px 34px {rgba(t.ink, .07)}; animation: rise .5s both; animation-delay: {delay:.2f}s">'
            f'<div style="display: flex; flex-direction: column; gap: 4px; flex-grow: 1"><span style="font-family: {t.display_css}; font-size: 44px; font-weight: 800; '
            f'letter-spacing: -0.03em; line-height: 1">{t.text(str(sm.get("value", "")))}</span><span style="font-size: 14px; font-weight: 700; color: {t.muted}">'
            f'{t.text(sm.get("label", ""))}</span></div>{_ring(t, 112, 11, float(sm.get("frac", 0)), t.cta, delay + 0.2, icon("sparkle", 30, t.cta, 2.2))}</div>')


def _metric_tiles(ctx: Ctx, metrics: list[dict[str, Any]]) -> str:
    t = ctx.theme
    tiles = "".join(
        f'<div style="display: flex; flex-direction: column; gap: 6px; padding: 14px 12px; border-radius: 20px; background: {t.surface}; '
        f'box-shadow: 0 8px 22px {rgba(t.ink, .05)}; animation: rise .5s both; animation-delay: {0.25 + i * 0.05:.2f}s">'
        f'<span style="width: 10px; height: 10px; border-radius: 5px; background: {t.series[i % len(t.series)]}"></span>'
        f'<span style="font-family: {t.display_css}; font-size: 20px; font-weight: 800">{t.text(str(m.get("value", "")))}</span>'
        f'<span style="font-size: 12px; font-weight: 700; color: {t.muted}">{t.text(m.get("label", ""))}</span></div>' for i, m in enumerate(metrics[:3]))
    return f'<div style="display: grid; grid-template-columns: repeat({max(1, min(3, len(metrics)))}, minmax(0, 1fr)); gap: 10px">{tiles}</div>' if metrics else ""


def _item_row(ctx: Ctx, it: dict[str, Any], d: float, href: str) -> str:
    t = ctx.theme
    return (f'<a href="{href}" style="display: flex; align-items: center; gap: 12px; padding: 10px 12px 10px 10px; border-radius: 20px; background: {t.surface}; '
            f'box-shadow: 0 8px 22px {rgba(t.ink, .05)}; animation: rise .5s both; animation-delay: {d:.2f}s">'
            f'<span style="width: 60px; height: 60px; border-radius: 16px; background: {t.selected}; display: flex; align-items: center; justify-content: center; '
            f'flex-shrink: 0">{icon(it.get("icon", "image"), 26, t.accent_text, 2)}</span><span style="display: flex; flex-direction: column; gap: 4px; flex-grow: 1; '
            f'min-width: 0"><strong style="font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">{t.text(it.get("title", ""))}</strong>'
            f'<span style="font-size: 12px; font-weight: 700; color: {t.soft}">{t.text(it.get("sub", ""))}</span></span>'
            f'{icon("chevron", 16, t.faint, 2.4)}</a>')


def _first_of(ctx: Ctx, kind: str) -> str:
    for s in ctx.doc.get("main", []):
        if s.get("kind") == kind:
            return ctx.href(s["id"])
    return "#"


def home(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    items = "".join(_item_row(ctx, it, 0.4 + i * 0.06, _first_of(ctx, "result")) for i, it in enumerate((s.get("items") or [])[:3]))
    body = (WRAP + topbar(ctx, t.display_name, _pill(ctx, s.get("streak", "5")), s.get("key")) + _WEEK
            + f'<div style="display: flex; flex-direction: column; gap: 14px; padding: 14px 20px 0">' + _summary(ctx, s) + _metric_tiles(ctx, s.get("metrics") or [])
            + (f'<div style="display: flex; justify-content: space-between; align-items: baseline; margin-top: 4px"><strong{l10n(s.get("key"), "recent")} style="font-size: 17px">'
               f'{t.text(s.get("recent_title", "Recent"))}</strong><a href="{_first_of(ctx, "history")}" style="font-size: 13px; font-weight: 800; color: {t.accent_text}">See all</a></div>'
               if items else "")
            + items + "</div></div>" + tabbar(ctx, s.get("tab")))
    return page(t, s["title"], body, _week_js(ctx, [True, True, True, True, False, False, False]))


def empty(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    cx = _capture_center_x(ctx) or 195
    pulses = "".join(f'<div aria-hidden="true" style="position: absolute; left: {cx - 32:.0f}px; top: 734px; width: 64px; height: 64px; border-radius: 32px; '
                     f'border: 3px solid {t.cta}; box-sizing: border-box; z-index: 6; pointer-events: none; animation: pulse 2.4s ease-out infinite; '
                     f'animation-delay: {d:.1f}s"></div>' for d in (0, 1.2)) if _capture_href(ctx) else ""
    badge = (f'<span style="display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 999px; background: {t.selected}; font-size: 13px; '
             f'font-weight: 800; color: {t.accent_text}">{icon("gift", 14, t.accent_text, 2.2)}{t.text(s["badge"])}</span>') if s.get("badge") else ""
    body = (WRAP + topbar(ctx, t.display_name, _pill(ctx, "0")) + _WEEK
            + f'<div style="display: flex; flex-direction: column; gap: 14px; padding: 14px 20px 0">'
              f'<div style="position: relative; display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 22px 20px; border-radius: 28px; '
              f'background: {t.surface}; box-shadow: 0 14px 34px {rgba(t.ink, .06)}; text-align: center; animation: rise .5s both; animation-delay: .25s">'
            + mascot(ctx, s.get("mascot", "wave"), 150, "bob 2.6s ease-in-out infinite")
            + titles(t, s["title"], s.get("subtitle"), s.get("key"), delay=0.3, center=True, size=24) + badge + "</div></div></div>"
            + pulses + tabbar(ctx, s.get("tab")))
    return page(t, s["title"], body, _week_js(ctx, [False] * 7))


def capture(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    modes = s.get("modes") or ["Photo"]
    mode_html = "".join(
        (f'<span style="padding: 8px 16px; border-radius: 999px; background: #FFFFFF; color: {t.ink}; font-size: 14px; font-weight: 800">{t.text(m)}</span>' if i == 0 else
         f'<a href="{_first_of(ctx, "text_input") if i == 1 else "#"}" style="padding: 8px 16px; border-radius: 999px; color: #FFFFFF; font-size: 14px; font-weight: 800">{t.text(m)}</a>')
        for i, m in enumerate(modes))
    brackets = "".join(f'<div style="position: absolute; {p}; width: 46px; height: 46px; border-color: {t.accent}; border-style: solid; border-width: {bw}; border-radius: {br}"></div>'
                       for p, bw, br in [("left: 0; top: 0", "5px 0 0 5px", "22px 0 0 0"), ("right: 0; top: 0", "5px 5px 0 0", "0 22px 0 0"),
                                         ("left: 0; bottom: 0", "0 0 5px 5px", "0 0 0 22px"), ("right: 0; bottom: 0", "0 5px 5px 0", "0 0 22px 0")])
    free = (f'<span style="padding: 7px 12px; border-radius: 999px; background: rgba(255,255,255,.14); color: #FFFFFF; font-size: 12px; font-weight: 800">'
            f'{t.text(s["free_badge"])}</span>') if s.get("free_badge") else "<span></span>"
    body = (f'<div style="position: absolute; inset: 0; background: #141110"></div>'
            f'<div style="position: absolute; left: 0; right: 0; top: 0; height: 620px; background: radial-gradient(120% 80% at 50% 40%, {rgba(t.accent, .35)} 0%, #1E1814 70%)"></div>'
            f'<div style="position: relative; display: flex; align-items: center; justify-content: space-between; padding: 56px 20px 0; z-index: 2">'
            f'<a href="{_first_of(ctx, "home")}" aria-label="Close" style="width: 40px; height: 40px; border-radius: 20px; background: rgba(255,255,255,.14); display: flex; '
            f'align-items: center; justify-content: center">{icon("close", 18, "#FFFFFF", 2.4)}</a><span{l10n(s.get("key"), "title")} style="color: #FFFFFF; font-size: 17px; '
            f'font-weight: 800">{t.text(s["title"])}</span>{free}</div>'
            f'<div style="position: relative; flex-grow: 1; display: flex; align-items: center; justify-content: center"><div style="position: relative; width: 300px; '
            f'height: 300px; display: flex; align-items: center; justify-content: center"><div style="width: 230px; height: 230px; border-radius: 40px; '
            f'background: {rgba("#FFFFFF", .06)}; animation: pop .6s both"></div>{brackets}<div style="position: absolute; left: 14px; right: 14px; top: 40px; height: 3px; '
            f'border-radius: 2px; background: {t.accent}; box-shadow: 0 0 18px 5px {rgba(t.accent, .5)}; animation: scan 2.8s ease-in-out infinite"></div></div>'
            f'<span style="position: absolute; bottom: 24px; padding: 8px 14px; border-radius: 999px; background: rgba(0,0,0,.45); color: #FFFFFF; font-size: 13px; '
            f'font-weight: 700">{t.text(s.get("hint", ""))}</span></div>'
            f'<div style="position: relative; display: flex; flex-direction: column; align-items: center; gap: 22px; padding: 18px 24px 40px; z-index: 2">'
            f'<div style="display: flex; gap: 6px; padding: 4px; border-radius: 999px; background: rgba(255,255,255,.1)">{mode_html}</div>'
            f'<div style="display: flex; align-items: center; justify-content: space-between; align-self: stretch; padding: 0 12px">'
            f'<button type="button" aria-label="Flash" style="width: 48px; height: 48px; border-radius: 24px; border: none; background: rgba(255,255,255,.14); display: flex; '
            f'align-items: center; justify-content: center; cursor: pointer">{icon("bolt", 20, "#FFFFFF", 2.2)}</button>'
            f'<a href="{_first_of(ctx, "analyzing")}" aria-label="Take photo" style="width: 80px; height: 80px; border-radius: 40px; border: 5px solid #FFFFFF; box-sizing: border-box; '
            f'display: flex; align-items: center; justify-content: center"><span style="width: 60px; height: 60px; border-radius: 30px; background: {t.cta}"></span></a>'
            f'<span style="width: 48px; height: 48px; border-radius: 14px; border: 2px solid rgba(255,255,255,.6); display: flex; align-items: center; justify-content: center; '
            f'background: #2A221D">{icon("image", 22, "#FFFFFF", 2)}</span></div></div>')
    return page(t, s["title"], '<div style="position: absolute; inset: 0; display: flex; flex-direction: column">' + body + "</div>")


def analyzing(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    steps = s.get("steps") or []

    def step(txt: str, state: str, d: float) -> str:
        mark = {"done": f'<span style="width: 24px; height: 24px; border-radius: 12px; background: {t.success}; display: flex; align-items: center; justify-content: center">'
                        f'{icon("check", 13, "#FFFFFF", 3.4)}</span>',
                "run": f'<span style="width: 24px; height: 24px; border-radius: 12px; border: 3px solid {t.selected}; border-top-color: {t.cta}; box-sizing: border-box; '
                       f'animation: spin .9s linear infinite"></span>',
                "wait": f'<span style="width: 24px; height: 24px; border-radius: 12px; border: 3px solid {t.line}; box-sizing: border-box"></span>'}[state]
        return (f'<div style="display: flex; align-items: center; gap: 12px; font-size: 15px; font-weight: 700; animation: rise .4s both; animation-delay: {d:.2f}s">'
                f'{mark}<span style="color: {t.ink if state != "wait" else t.soft}">{t.text(txt)}</span></div>')
    rows = "".join(step(x, "done" if i == 0 else ("run" if i == 1 else "wait"), 0.2 + i * 0.1) for i, x in enumerate(steps))
    body = (f'<div style="flex-grow: 1; display: flex; flex-direction: column; gap: 24px; padding: 64px 24px 0">'
            f'<div style="position: relative; height: 330px; border-radius: 32px; overflow: hidden; background: radial-gradient(circle at 50% 45%, {t.selected}, {t.glow}); '
            f'display: flex; align-items: center; justify-content: center; animation: pop .6s both">{icon("image", 120, rgba(t.ink, .18), 1.2)}'
            f'<div style="position: absolute; left: 0; right: 0; top: 0; height: 90px; background: linear-gradient(180deg, {rgba(t.accent, 0)}, {rgba(t.accent, .28)}, {rgba(t.accent, 0)}); '
            f'animation: scan 2.4s ease-in-out infinite"></div><div style="position: absolute; right: 12px; bottom: 6px">'
            f'{mascot(ctx, s.get("mascot", "think"), 96, "bob 2s ease-in-out infinite")}</div></div>'
            + titles(t, s["title"], s.get("subtitle"), s.get("key"), delay=0.1, size=28)
            + f'<div style="display: flex; flex-direction: column; gap: 14px">{rows}</div></div>'
              f'<div style="padding: 12px 24px 34px; height: 104px; box-sizing: border-box"><a href="{_first_of(ctx, "result")}" style="display: flex; align-items: center; '
              f'justify-content: center; height: 58px; border-radius: 29px; background: {t.cta}; color: #FFFFFF; font-size: 19px; font-weight: 800; animation: fadein .4s both; '
              f'animation-delay: 2.6s">See result</a></div>')
    return page(t, s["title"], body)


def result(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    items = (s.get("items") or [])[:4]
    rows = "".join(
        f'<div style="display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid {t.line}">'
        f'<strong style="font-size: 15px; flex-grow: 1">{t.text(x)}</strong><span style="display: flex; align-items: center; gap: 4px; padding: 3px; border-radius: 14px; '
        f'background: {t.line}"><button type="button" onClick="{b(f"i{i}.minus")}" aria-label="Less" style="width: 32px; height: 32px; border: none; border-radius: 11px; '
        f'background: {t.surface}; font-size: 18px; font-weight: 800; cursor: pointer">−</button><span style="min-width: 36px; text-align: center; font-size: 14px; font-weight: 800; '
        f'font-variant-numeric: tabular-nums">{b(f"i{i}.v")}</span><button type="button" onClick="{b(f"i{i}.plus")}" aria-label="More" style="width: 32px; height: 32px; '
        f'border: none; border-radius: 11px; background: {t.surface}; font-size: 18px; font-weight: 800; cursor: pointer">+</button></span></div>' for i, x in enumerate(items))
    tiles = "".join(f'<div style="display: flex; flex-direction: column; gap: 6px; padding: 12px; border-radius: 18px; background: {t.bg}">'
                    f'<span style="display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 800; color: {t.muted}"><span style="width: 8px; height: 8px; '
                    f'border-radius: 4px; background: {t.series[i % len(t.series)]}"></span>{t.text(x.get("label", ""))}</span><span style="font-family: {t.display_css}; '
                    f'font-size: 22px; font-weight: 800">{t.text(str(x.get("value", "")))}</span></div>' for i, x in enumerate((s.get("tiles") or [])[:3]))
    score = (f'<span style="display: flex; flex-direction: column; align-items: center; padding: 8px 10px; border-radius: 16px; background: {t.success_fill}; flex-shrink: 0">'
             f'<strong style="font-size: 18px; color: {t.success_text}">{s["score"]}/10</strong><span style="font-size: 11px; font-weight: 800; color: {t.success_text}">'
             f'{t.text(s.get("score_label", "Score"))}</span></span>') if s.get("score") is not None else ""
    body = (f'<div style="position: absolute; left: 0; right: 0; top: 0; height: 250px; background: radial-gradient(circle at 50% 55%, {t.selected}, {t.glow}); display: flex; '
            f'align-items: center; justify-content: center"><div style="animation: pop .6s both">{icon("image", 110, rgba(t.ink, .2), 1.2)}</div></div>'
            f'<div style="position: absolute; top: 54px; left: 20px; right: 20px; display: flex; justify-content: space-between; z-index: 3">'
            f'<a href="{_first_of(ctx, "home")}" aria-label="Back" style="width: 40px; height: 40px; border-radius: 20px; background: rgba(255,255,255,.85); display: flex; '
            f'align-items: center; justify-content: center">{icon("back", 20, t.ink, 2.2)}</a></div>'
            f'<div style="position: absolute; left: 0; right: 0; top: 222px; bottom: 0; border-radius: 30px 30px 0 0; background: {t.surface}; display: flex; flex-direction: column; '
            f'padding: 20px 20px 0; gap: 14px; box-shadow: 0 -10px 30px {rgba(t.ink, .06)}; animation: rise .5s both">'
            f'<div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px"><div style="display: flex; flex-direction: column; gap: 6px">'
            f'<span style="align-self: flex-start; padding: 4px 10px; border-radius: 999px; background: {t.selected}; font-size: 12px; font-weight: 800; color: {t.accent_text}">'
            f'{t.text(s.get("tag", ""))}</span><h1{l10n(s.get("key"), "title")} style="margin: 0; font-family: {t.display_css}; font-size: 26px; line-height: 1.08; font-weight: 800; '
            f'letter-spacing: -0.025em">{t.text(s["title"])}</h1></div>{score}</div>'
            f'<div style="display: flex; align-items: baseline; gap: 10px"><span style="font-family: {t.display_css}; font-size: 40px; font-weight: 800; letter-spacing: -0.03em">'
            f'{t.text(str(s.get("headline_value", "")))}</span><span style="font-size: 16px; font-weight: 700; color: {t.muted}">{t.text(s.get("headline_unit", ""))}</span></div>'
            f'<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px">{tiles}</div>'
            f'<div style="display: flex; flex-direction: column; margin-top: -4px">{rows}</div>'
            f'<div style="margin-top: auto; padding: 10px 0 30px; display: flex; gap: 10px"><a href="{_first_of(ctx, "home")}" style="flex-grow: 1; display: flex; '
            f'align-items: center; justify-content: center; height: 56px; border-radius: 28px; background: {t.cta}; color: #FFFFFF; font-size: 19px; font-weight: 800; '
            f'box-shadow: 0 12px 26px {t.cta_shadow}">{t.text(s.get("cta", "Save"))}</a></div></div>')
    js = f"""renderVals() {{
  var self = this;
  var st = this.state || {{}}, out = {{}};
  for (var i = 0; i < {len(items)}; i++) (function (i) {{
    var v = st["v" + i] != null ? st["v" + i] : 1;
    out["i" + i] = {{ v: v + "×", minus: function () {{ var o = {{}}; o["v" + i] = Math.max(0, v - 1); self.setState(o); }},
      plus: function () {{ var o = {{}}; o["v" + i] = v + 1; self.setState(o); }} }};
  }})(i);
  return out;
}}"""
    return page(t, s["title"], body, js)


def text_input(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    sug = "".join(f'<button type="button" style="padding: 9px 14px; border-radius: 999px; border: 1.5px solid {t.line}; background: {t.surface}; font-size: 14px; '
                  f'font-weight: 700; cursor: pointer; animation: pop .4s both; animation-delay: {0.2 + i * 0.05:.2f}s">{t.text(x)}</button>'
                  for i, x in enumerate(s.get("suggestions") or []))
    tip = (f'<div style="display: flex; gap: 12px; align-items: center; padding: 14px 16px; border-radius: 18px; background: {t.surface}; border: 1.5px solid {t.line}">'
           f'{mascot(ctx, s.get("mascot", "think"), 44, "none")}<span style="font-size: 13px; line-height: 1.4; color: {t.muted}">{t.text(s["tip"])}</span></div>') if s.get("tip") else ""
    body = (f'<div style="display: flex; align-items: center; gap: 14px; padding: 56px 24px 0"><a href="{_first_of(ctx, "capture")}" aria-label="Back" style="width: 44px; '
            f'height: 44px; border-radius: 22px; background: {t.surface}; border: 1.5px solid {t.line}; display: flex; align-items: center; justify-content: center; '
            f'box-sizing: border-box">{icon("back", 20, t.ink, 2.2)}</a></div>'
            + content(titles(t, s["title"], s.get("subtitle"), s.get("key"))
                      + f'<div style="position: relative; animation: rise .5s both; animation-delay: .15s"><textarea rows="4" aria-label="{t.text(s["title"])}" '
                        f'placeholder="{t.text(s.get("placeholder", ""))}" style="width: 100%; box-sizing: border-box; resize: none; padding: 16px 52px 16px 16px; '
                        f'border-radius: 20px; border: 2px solid {t.accent}; background: {t.surface}; font-family: inherit; font-size: 17px; line-height: 1.45; '
                        f'color: {t.ink}; outline: none"></textarea><button type="button" aria-label="Dictate" style="position: absolute; right: 10px; bottom: 12px; '
                        f'width: 36px; height: 36px; border-radius: 18px; border: none; background: {t.selected}; display: flex; align-items: center; justify-content: center; '
                        f'cursor: pointer">{icon("mic", 18, t.accent_text, 2.2)}</button></div>'
                      + f'<div style="display: flex; flex-wrap: wrap; gap: 8px">{sug}</div>' + tip, gap=22)
            + cta(t, _first_of(ctx, "analyzing"), s.get("cta", "Continue"), key=s.get("key")))
    return page(t, s["title"], body)


def progress(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    bars = s.get("bars") or [5, 7, 6, 4, 8, 6, 3]
    top = max(bars) or 1
    bar_html = "".join(f'<div style="display: flex; flex-direction: column; align-items: center; gap: 6px; flex: 1"><div style="width: 100%; max-width: 26px; '
                       f'height: {int(v / top * 110)}px; border-radius: 8px; background: {t.cta}; transform-origin: bottom; animation: growY .7s cubic-bezier(.2,.8,.2,1) both; '
                       f'animation-delay: {0.3 + i * 0.06:.2f}s"></div><span style="font-size: 11px; font-weight: 800; color: {t.soft}">{"MTWTFSS"[i % 7]}</span></div>'
                       for i, v in enumerate(bars[:7]))
    body = (WRAP + topbar(ctx, s["title"], key=s.get("key"))
            + f'<div style="display: flex; flex-direction: column; gap: 14px; padding: 16px 20px 0">' + _summary(ctx, s, 0.05)
            + f'<div style="display: flex; flex-direction: column; gap: 10px; padding: 16px 18px; border-radius: 26px; background: {t.surface}; '
              f'box-shadow: 0 12px 30px {rgba(t.ink, .06)}; animation: rise .5s both; animation-delay: .2s"><strong style="font-size: 15px">{t.text(s.get("chart_title", "This week"))}</strong>'
              f'<div style="display: flex; align-items: flex-end; gap: 10px; height: 132px">{bar_html}</div></div></div></div>' + tabbar(ctx, s.get("tab")))
    return page(t, s["title"], body)


def history(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    days = "".join(
        f'<a href="{_first_of(ctx, "home")}" style="display: flex; align-items: center; gap: 14px; padding: 14px 16px; border-radius: 22px; background: {t.surface}; '
        f'box-shadow: 0 8px 22px {rgba(t.ink, .05)}; animation: rise .5s both; animation-delay: {0.1 + i * 0.06:.2f}s">'
        f'{_ring(t, 46, 6, 1.0 if i else 0.4, t.cta, 0.3 + i * 0.06)}<span style="display: flex; justify-content: space-between; flex-grow: 1">'
        f'<strong style="font-size: 15px">{t.text(d.get("title", ""))}</strong><span style="font-size: 14px; font-weight: 800">{t.text(d.get("value", ""))}</span></span></a>'
        for i, d in enumerate((s.get("days") or [])[:5]))
    paywall_href = ctx.files.get(next((x["id"] for x in ctx.doc.get("onboarding", []) if x.get("kind") == "paywall"), ""), "#")
    locked = (f'<a href="{paywall_href}" style="display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 18px; border-radius: 22px; '
              f'background: {t.surface}; border: 2px dashed {t.glow}; text-align: center; animation: rise .5s both; animation-delay: .34s">'
              f'<span style="width: 40px; height: 40px; border-radius: 20px; background: {t.selected}; display: flex; align-items: center; justify-content: center">'
              f'{icon("lock", 18, t.accent_text, 2.2)}</span><strong style="font-size: 15px">{t.text(s["locked"])}</strong>'
              f'<span style="font-size: 13px; color: {t.muted}">{t.text(s.get("locked_sub", ""))}</span></a>') if s.get("locked") else ""
    body = (WRAP + topbar(ctx, s["title"], key=s.get("key"))
            + f'<div style="display: flex; flex-direction: column; gap: 12px; padding: 18px 20px 0">{days}{locked}</div></div>' + tabbar(ctx, s.get("tab")))
    return page(t, s["title"], body)


def settings(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    weight_units = bool(s.get("units")) or any(r.get("right") == "units" for g in s.get("groups") or [] for r in g.get("rows") or [])

    def row(r: dict[str, Any], last: bool) -> str:
        danger = r.get("danger")
        col = "#C2261A" if danger else t.ink
        right = {
            "units": (f'<span style="display: flex; padding: 3px; border-radius: 10px; background: {t.line}; gap: 2px">'
                      f'<button type="button" onClick="{b("toKg")}" style="width: 38px; height: 28px; border: none; border-radius: 8px; font-size: 13px; font-weight: 800; '
                      f'background: {b("kgBg")}; color: {b("kgC")}; cursor: pointer">kg</button><button type="button" onClick="{b("toLb")}" style="width: 38px; height: 28px; '
                      f'border: none; border-radius: 8px; font-size: 13px; font-weight: 800; background: {b("lbBg")}; color: {b("lbC")}; cursor: pointer">lb</button></span>'),
            "toggle": (f'<button type="button" role="switch" aria-checked="{b("tOn")}" onClick="{b("tTog")}" style="width: 50px; height: 30px; border-radius: 15px; border: none; '
                       f'padding: 3px; background: {b("tBg")}; cursor: pointer; display: flex; transition: background .25s"><span style="width: 24px; height: 24px; '
                       f'border-radius: 12px; background: #FFFFFF; box-shadow: 0 2px 6px {rgba(t.ink, .25)}; transform: translateX({b("tX")}px); '
                       f'transition: transform .3s cubic-bezier(.3,1.5,.5,1)"></span></button>'),
        }.get(r.get("right", ""), icon("chevron", 16, t.faint, 2.4))
        return (f'<div style="display: flex; align-items: center; gap: 12px; height: 46px; {"" if last else f"border-bottom: 1px solid {t.line};"}">'
                f'<span style="width: 30px; height: 30px; border-radius: 9px; background: {"#FDE4E1" if danger else t.selected}; display: flex; align-items: center; '
                f'justify-content: center; flex-shrink: 0">{icon(r.get("icon", "dots"), 16, "#C2261A" if danger else t.accent_text, 2.2)}</span>'
                f'<span style="flex-grow: 1; font-size: 15px; font-weight: 700; color: {col}">{t.text(r["label"])}</span>{right}</div>')
    groups = "".join(
        f'<div style="display: flex; flex-direction: column; gap: 8px; animation: rise .5s both; animation-delay: {0.08 + gi * 0.06:.2f}s">'
        f'<span style="font-size: 12px; font-weight: 800; color: {t.muted}; letter-spacing: .05em; padding-left: 4px">{t.text(g.get("title", ""))}</span>'
        f'<div style="padding: 2px 14px; border-radius: 20px; background: {t.surface}; box-shadow: 0 8px 22px {rgba(t.ink, .04)}">'
        + "".join(row(r, i == len(g["rows"]) - 1) for i, r in enumerate(g.get("rows") or [])) + "</div></div>"
        for gi, g in enumerate(s.get("groups") or []))
    profile = (f'<div style="display: flex; align-items: center; gap: 14px; padding: 14px 16px; border-radius: 24px; background: linear-gradient(135deg, {t.glow}, {t.selected}); '
               f'animation: rise .5s both"><span style="width: 58px; height: 58px; border-radius: 18px; background: {t.surface}; display: flex; align-items: flex-end; '
               f'justify-content: center; overflow: hidden; flex-shrink: 0">{mascot(ctx, s.get("mascot", "wave"), 54, "none", extra="margin-bottom: -6px")}</span>'
               f'<span style="display: flex; flex-direction: column; gap: 3px; flex-grow: 1"><strong style="font-size: 16px">{t.text(s.get("profile", ""))}</strong>'
               f'<span style="display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 700; color: {t.accent_text}">{icon("sparkle", 13, t.accent_text, 2.2)}'
               f'{t.text(s.get("premium_line", "{app} Premium"))}</span></span></div>')
    body = (WRAP + topbar(ctx, s["title"], key=s.get("key"))
            + f'<div style="display: flex; flex-direction: column; gap: 14px; padding: 16px 20px 0">{profile}{groups}</div></div>' + tabbar(ctx, s.get("tab")))
    js = f"""renderVals() {{
  var self = this;
  var st = this.state || {{}};
  var lb = st.unit === "lb", tg = st.t != null ? st.t : true;
  var on = {{ bg: "{t.surface}", c: "{t.ink}" }}, off = {{ bg: "transparent", c: "{t.soft}" }};
  var a = lb ? off : on, c = lb ? on : off;
  return {{
    kgBg: a.bg, kgC: a.c, lbBg: c.bg, lbC: c.c,
    toKg: function () {{ self.setState({{ unit: "kg" }}); }}, toLb: function () {{ self.setState({{ unit: "lb" }}); }},
    tOn: tg ? "true" : "false", tBg: tg ? "{t.success}" : "{t.faint}", tX: tg ? 20 : 0, tTog: function () {{ self.setState({{ t: !tg }}); }}
  }};
}}""" if weight_units or any(r.get("right") == "toggle" for g in s.get("groups") or [] for r in g.get("rows") or []) else "renderVals() { return {}; }"
    return page(t, s["title"], body, js)


def limit_sheet(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    body = (f'<div style="position: absolute; inset: 0; background: {rgba(t.ink, .42)}; z-index: 1; animation: fadein .3s both"></div>'
            f'<div style="position: absolute; inset: 0; filter: blur(2px); opacity: .9">{WRAP}{topbar(ctx, t.display_name)}<div style="padding: 90px 20px 0">'
            f'{_summary(ctx, {"summary": {"value": "0", "label": "", "frac": 1}}, 0)}</div></div></div>'
            f'<div role="dialog" aria-label="{t.text(s["title"])}" style="position: absolute; left: 0; right: 0; bottom: 0; z-index: 2; display: flex; flex-direction: column; '
            f'align-items: center; gap: 12px; padding: 16px 24px 34px; border-radius: 30px 30px 0 0; background: {t.bg}; text-align: center; animation: rise .45s cubic-bezier(.2,.8,.2,1) both">'
            f'<span style="width: 40px; height: 5px; border-radius: 3px; background: {t.faint}"></span>'
            + mascot(ctx, s.get("mascot", "sleep"), 120, "bob 2.4s ease-in-out infinite")
            + titles(t, s["title"], s.get("subtitle"), s.get("key"), delay=0.1, center=True, size=24)
            + (f'<a href="{_first_of(ctx, "text_input")}" style="align-self: stretch; display: flex; align-items: center; justify-content: center; height: 58px; margin-top: 6px; '
               f'border-radius: 29px; background: {t.cta}; color: #FFFFFF; font-size: 19px; font-weight: 800">{t.text(s["secondary"])}</a>' if s.get("secondary") else "")
            + f'<a href="{_first_of(ctx, "home")}" style="font-size: 15px; font-weight: 800; color: {t.muted}; padding: 6px">{t.text(s.get("cta", "OK"))}</a></div>')
    return page(t, s["title"], body)


def list_screen(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    items = "".join(_item_row(ctx, it if isinstance(it, dict) else {"title": it}, 0.1 + i * 0.06, "#") for i, it in enumerate((s.get("items") or [])[:6]))
    body = (WRAP + topbar(ctx, s["title"], key=s.get("key"))
            + f'<div style="display: flex; flex-direction: column; gap: 12px; padding: 18px 20px 0">{items}</div></div>' + tabbar(ctx, s.get("tab")))
    return page(t, s["title"], body)


RENDERERS: dict[str, Callable[[Ctx, dict[str, Any]], str]] = {
    "home": home, "empty": empty, "capture": capture, "analyzing": analyzing, "result": result,
    "text_input": text_input, "progress": progress, "history": history, "settings": settings,
    "limit_sheet": limit_sheet, "list": list_screen,
}
