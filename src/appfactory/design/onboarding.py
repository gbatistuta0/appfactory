"""Onboarding board renderers — one function per screen kind (Cal AI funnel, honest)."""

from __future__ import annotations

import datetime
import json
from typing import Any, Callable

from . import pricing
from .dc import (ICONS, Ctx, app_mark, card, cta, check_badge, content, floating_hearts, header, icon, l10n,
                 mascot, page, pulse_rings, segmented, segmented_js, sparkle_confetti, titles)
from .screens import is_weight_picker
from .theme import rgba


def b(name: str) -> str:
    """A `{{binding}}` hole."""
    return "{{" + name + "}}"


# ------------------------------------------------------------ questions

def _option(ctx: Ctx, k: str, opt: dict[str, Any], delay: float, compact: bool, key: str | None, i: int) -> str:
    t = ctx.theme
    h = 58 if compact else 72
    ic = opt.get("icon")
    size = 36 if compact else 44
    icb = (f'<div style="width: {size}px; height: {size}px; border-radius: 50%; background: {b(k + ".ib")}; display: flex; '
           f'align-items: center; justify-content: center; flex-shrink: 0; transition: background .25s; color: {b(k + ".ic")}">'
           f'{icon(ic, 19 if compact else 22, "currentColor")}</div>') if ic else ""
    sub = (f'<span{l10n(key, f"option{i}.sub")} style="font-size: 13px; line-height: 1.3; color: {t.muted}">{t.text(opt["sub"])}</span>'
           if opt.get("sub") else "")
    return (f'<button type="button" onClick="{b(k + ".pick")}" aria-pressed="{b(k + ".on")}" style="display: flex; align-items: center; '
            f'gap: 14px; width: 100%; min-height: {h}px; padding: 10px 16px 10px {12 if ic else 20}px; box-sizing: border-box; '
            f'border-radius: 20px; border: 2px solid {b(k + ".bd")}; background: {b(k + ".bg")}; text-align: left; cursor: pointer; '
            f'transform: scale({b(k + ".sc")}); transition: background .25s, border-color .25s, transform .25s cubic-bezier(.3,1.6,.5,1); '
            f'animation: rise .5s cubic-bezier(.2,.8,.2,1) both; animation-delay: {delay:.2f}s">'
            f'{icb}<span style="display: flex; flex-direction: column; gap: 2px; flex-grow: 1">'
            f'<span{l10n(key, f"option{i}")} style="font-size: {16 if compact else 17}px; font-weight: 700; line-height: 1.2">{t.text(opt["label"])}</span>{sub}</span>'
            f'{check_badge(t, k)}</button>')


def _chip(ctx: Ctx, k: str, opt: dict[str, Any], delay: float, key: str | None, i: int) -> str:
    t = ctx.theme
    dot = opt.get("color") or t.series[i % len(t.series)]
    return (f'<button type="button" onClick="{b(k + ".pick")}" aria-pressed="{b(k + ".on")}" style="position: relative; display: flex; '
            f'align-items: center; gap: 10px; min-width: 0; height: 56px; padding: 0 12px 0 14px; box-sizing: border-box; border-radius: 18px; '
            f'border: 2px solid {b(k + ".bd")}; background: {b(k + ".bg")}; cursor: pointer; transition: background .25s, border-color .25s; '
            f'animation: pop .45s cubic-bezier(.2,.8,.2,1) both; animation-delay: {delay:.2f}s">'
            f'<span style="width: 12px; height: 12px; border-radius: 6px; background: {dot}; flex-shrink: 0"></span>'
            f'<span{l10n(key, f"option{i}")} style="font-size: 15px; font-weight: 700; flex-grow: 1; min-width: 0; text-align: left; '
            f'white-space: nowrap; overflow: hidden; text-overflow: ellipsis">{t.text(opt["label"])}</span>'
            f'<span style="position: absolute; top: -8px; right: -6px; width: 24px; height: 24px; border-radius: 12px; box-sizing: border-box; '
            f'border: 2px solid {t.bg}; background: {t.accent}; display: flex; align-items: center; justify-content: center; '
            f'opacity: {b(k + ".co")}; transform: scale({b(k + ".co")}); transition: all .3s cubic-bezier(.3,1.6,.5,1)">'
            f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.4" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{ICONS["check"]}</svg></span></button>')


def _question_js(ctx: Ctx, n: int, default: list[int], multi: bool) -> str:
    t = ctx.theme
    return f"""renderVals() {{
  var self = this;
  var DEF = {json.dumps(default)};
  var st = this.state || {{}};
  var sel = st.sel || DEF;
  function opt(i) {{
    var on = sel.indexOf(i) >= 0;
    return {{
      on: on ? "true" : "false",
      bg: on ? "{t.selected}" : "{t.surface}",
      bd: on ? "{t.accent}" : "{t.line}",
      ib: on ? "{t.accent}" : "{t.icon_bg}",
      ic: on ? "#FFFFFF" : "{t.accent_text}",
      cb: on ? "{t.accent}" : "transparent",
      cbd: on ? "{t.accent}" : "{t.faint}",
      co: on ? 1 : 0,
      sc: on ? 1.02 : 1,
      pick: function () {{
        var cur = (self.state || {{}}).sel || DEF;
        var next = {"cur.indexOf(i) >= 0 ? cur.filter(function (x) { return x !== i; }) : cur.concat([i])" if multi else "[i]"};
        self.setState({{ sel: next }});
      }}
    }};
  }}
  var out = {{ ctaBg: sel.length ? "{t.cta}" : "{t.cta_disabled}" }};
  for (var i = 0; i < {n}; i++) {{ out["o" + i] = opt(i); }}
  return out;
}}"""


def question(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    t, key = ctx.theme, s.get("key")
    opts = s["options"]
    multi = s.get("select") == "multi"
    layout = s.get("layout", "list")
    if layout == "grid":
        items = "".join(_chip(ctx, f"o{j}", o, 0.12 + j * 0.05, key, j) for j, o in enumerate(opts))
        lst = f'<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 10px; padding-top: 6px">{items}</div>'
    else:
        compact = layout == "compact"
        items = "".join(_option(ctx, f"o{j}", o, 0.12 + j * 0.06, compact, key, j) for j, o in enumerate(opts))
        lst = f'<div style="display: flex; flex-direction: column; gap: {10 if compact else 12}px">{items}</div>'
    hint = (f'<span{l10n(key, "hint")} style="font-size: 13px; font-weight: 600; color: {t.muted}; margin-top: -14px">Select all that apply</span>'
            if multi else "")
    body = (header(t, nav["prev"], nav["frac"], nav["prev_frac"])
            + content(titles(t, s["title"], s.get("subtitle"), key) + hint + lst, gap=22 if layout == "compact" else 28)
            + cta(t, nav["next"], s.get("cta", "Continue"), bg=b("ctaBg"), key=key))
    return page(t, s["title"], body, _question_js(ctx, len(opts), s.get("default", []), multi))


# ------------------------------------------------------------ pickers

WHEEL_JS = """wheel(key, list, def) {
  var self = this;
  var st = this.state || {};
  var idx = st[key] != null ? st[key] : def;
  if (!this._refs) { this._refs = {}; this._scr = {}; }
  if (!this._refs[key]) {
    this._refs[key] = function (el) { if (el && !el._init) { el._init = true; el.scrollTop = def * 44; } };
    this._scr[key] = function (e) {
      var t = e.currentTarget || e.target;
      var i = Math.max(0, Math.min(list.length - 1, Math.round(t.scrollTop / 44)));
      if (i !== (self.state || {})[key]) { var o = {}; o[key] = i; self.setState(o); }
    };
  }
  return {
    items: list.map(function (v, i) {
      var d = Math.abs(i - idx);
      return { v: v, fs: d === 0 ? 23 : 18, fw: d === 0 ? 800 : 500, c: d === 0 ? "INK" : "SOFT", op: d === 0 ? 1 : (d === 1 ? 0.75 : 0.45) };
    }),
    ref: this._refs[key],
    scroll: this._scr[key],
    value: list[idx]
  };
}
"""


def _wheel_js(ctx: Ctx) -> str:
    return WHEEL_JS.replace("INK", ctx.theme.ink).replace("SOFT", ctx.theme.soft)


def _wheel(ctx: Ctx, k: str, label: str | None = None, flex: float = 1) -> str:
    t = ctx.theme
    lab = f'<span style="font-size: 14px; font-weight: 700; color: {t.muted}; text-align: center">{t.text(label)}</span>' if label else ""
    return (f'<div style="flex: {flex}; display: flex; flex-direction: column; gap: 10px; min-width: 0">{lab}'
            f'<div style="position: relative; height: 220px">'
            f'<div style="position: absolute; left: 0; right: 0; top: 88px; height: 44px; border-radius: 14px; background: {t.surface}; '
            f'box-shadow: 0 6px 18px {rgba(t.ink, .07)}; border: 1.5px solid {t.line}; box-sizing: border-box"></div>'
            f'<div class="snap" ref="{b(k + ".ref")}" onScroll="{b(k + ".scroll")}" style="position: relative; height: 220px; overflow-y: auto; '
            f'scroll-snap-type: y mandatory; -webkit-mask-image: linear-gradient(transparent, #000 32%, #000 68%, transparent); '
            f'mask-image: linear-gradient(transparent, #000 32%, #000 68%, transparent)">'
            f'<div style="height: 88px"></div><sc-for list="{b(k + ".items")}" as="it" hint-placeholder-count="5">'
            f'<div style="height: 44px; display: flex; align-items: center; justify-content: center; scroll-snap-align: center; '
            f'font-size: {b("it.fs")}px; font-weight: {b("it.fw")}; color: {b("it.c")}; opacity: {b("it.op")}; '
            f'font-variant-numeric: tabular-nums; transition: font-size .15s, color .15s, opacity .15s; white-space: nowrap">{b("it.v")}</div>'
            f'</sc-for><div style="height: 88px"></div></div></div></div>')


def _big_number(ctx: Ctx, label: str | None, val: str, unit: str) -> str:
    t = ctx.theme
    lab = f'<span style="font-size: 15px; font-weight: 700; color: {t.muted}">{t.text(label)}</span>' if label else ""
    return (f'<div style="display: flex; flex-direction: column; align-items: center; gap: 6px; margin-top: 8px; animation: rise .5s both; '
            f'animation-delay: .12s">{lab}<div style="display: flex; align-items: baseline; gap: 6px">'
            f'<span style="font-family: {t.display_css}; font-size: 64px; font-weight: 800; letter-spacing: -0.04em; '
            f'font-variant-numeric: tabular-nums; line-height: 1">{val}</span>'
            f'<span style="font-size: 22px; font-weight: 700; color: {t.muted}">{unit}</span></div></div>')


def _ruler_markup(ctx: Ctx) -> str:
    t = ctx.theme
    return (f'<div style="position: relative; margin: 18px -24px 0; height: 120px; animation: rise .5s both; animation-delay: .22s">'
            f'<div class="snap" ref="{b("rRef")}" onScroll="{b("rScroll")}" style="height: 120px; overflow-x: auto; overflow-y: hidden; '
            f'scroll-snap-type: x mandatory; display: flex; align-items: flex-start; -webkit-mask-image: linear-gradient(90deg, transparent, #000 25%, #000 75%, transparent); '
            f'mask-image: linear-gradient(90deg, transparent, #000 25%, #000 75%, transparent)">'
            f'<div style="flex: 0 0 189px"></div><sc-for list="{b("ticks")}" as="t" hint-placeholder-count="40">'
            f'<div style="flex: 0 0 12px; height: 110px; display: flex; flex-direction: column; align-items: center; gap: 8px; scroll-snap-align: center">'
            f'<div style="width: 2px; height: {b("t.h")}px; border-radius: 1px; background: {b("t.c")}"></div>'
            f'<span style="font-size: 12px; font-weight: 700; color: {t.muted}; white-space: nowrap; opacity: {b("t.lo")}">{b("t.lab")}</span></div>'
            f'</sc-for><div style="flex: 0 0 189px"></div></div>'
            f'<div style="position: absolute; left: 193px; top: -6px; width: 4px; height: 72px; border-radius: 2px; background: {t.accent}; '
            f'box-shadow: 0 0 0 4px {rgba(t.accent, .18)}; pointer-events: none"></div></div>'
            f'<span style="text-align: center; font-size: 14px; color: {t.muted}; margin-top: -6px">Swipe to adjust</span>')


def _ruler_js(ctx: Ctx, ranges: str, default_expr: str, ref_expr: str, unit_expr: str, extra: str = "", seg: str = "") -> str:
    t = ctx.theme
    return f"""renderVals() {{
  var self = this;
  var st = this.state || {{}};
  {seg}
  var R = {ranges};
  var key = "i_" + R.u;
  var DEF = {default_expr};
  var idx = st[key] != null ? st[key] : DEF;
  if (!this._r) {{ this._r = {{}}; this._s = {{}}; }}
  if (!this._r[key]) {{
    this._r[key] = function (el) {{ if (el && !el._init) {{ el._init = true; el.scrollLeft = DEF * 12; }} }};
    this._s[key] = function (e) {{
      var t = e.currentTarget || e.target;
      var i = Math.max(0, Math.min(R.n, Math.round(t.scrollLeft / 12)));
      if (i !== (self.state || {{}})[key]) {{ var o = {{}}; o[key] = i; self.setState(o); }}
    }};
  }}
  var ticks = [];
  for (var k = 0; k <= R.n; k++) {{
    var major = k % R.major === 0, mid = k % R.mid === 0;
    ticks.push({{ h: major ? 56 : (mid ? 36 : 24), c: major ? "{t.ink}" : "{t.faint}", lab: major ? String(+(R.min + k * R.step).toFixed(1)) : "", lo: major ? 1 : 0 }});
  }}
  var val = R.min + idx * R.step, ref = {ref_expr}, d = val - ref, u = {unit_expr};
  var out = {{
    ticks: ticks, rRef: this._r[key], rScroll: this._s[key], val: (R.step < 1 ? val.toFixed(1) : String(val)), unit: u,
    delta: d === 0 ? "Same as now" : (d < 0 ? "−" : "+") + Math.abs(d).toFixed(R.step < 1 ? 1 : 0) + " " + u + " from now",
    deltaBg: d < 0 ? "{t.selected}" : "{t.line}", deltaC: d < 0 ? "{t.accent_text}" : "{t.muted}"
  }};
  {extra}
  return out;
}}"""


def _kg_lb_js(ctx: Ctx) -> str:
    return (segmented_js(ctx.theme, "kg", "lb", "unit", "lb")
            + '\n  var toKg = function () { self.setState({ unit: "kg" }); }, toLb = function () { self.setState({ unit: "lb" }); };')


_KG_LB_OUT = "for (var sk in seg) out[sk] = seg[sk]; out.toKg = toKg; out.toLb = toLb;"


def _picker_weight(ctx: Ctx, s: dict[str, Any], pk: dict[str, Any]) -> tuple[str, str]:
    """Horizontal ruler in kg (0.5 steps) or lb (1 lb steps) — the kg/lb toggle is always shown."""
    lo, hi = pk.get("min_kg", 40), pk.get("max_kg", 150)
    cur = pk.get("current_kg", 72)
    dflt = pk.get("default_kg", cur - 6)
    lo_lb, hi_lb = round(lo * 2.2046), round(hi * 2.2046)
    ranges = (f'st.unit === "lb" ? {{ u: "lb", min: {lo_lb}, step: 1, n: {hi_lb - lo_lb}, major: 10, mid: 5 }}'
              f' : {{ u: "kg", min: {lo}, step: 0.5, n: {int((hi - lo) * 2)}, major: 10, mid: 2 }}')
    default_expr = f'st.unit === "lb" ? {round(dflt * 2.2046) - lo_lb} : {int((dflt - lo) * 2)}'
    ref_expr = f'st.unit === "lb" ? {round(cur * 2.2046)} : {cur}'
    markup = (segmented(ctx.theme, ("kg", "kg"), ("lb", "lb"), width=72, center=True)
              + _big_number(ctx, pk.get("label"), b("val"), b("unit"))
              + f'<span style="align-self: center; padding: 6px 12px; border-radius: 999px; background: {b("deltaBg")}; color: {b("deltaC")}; '
                f'font-size: 14px; font-weight: 800; transition: all .25s">{b("delta")}</span>'
              + _ruler_markup(ctx))
    return markup, _ruler_js(ctx, ranges, default_expr, ref_expr, "R.u", _KG_LB_OUT, _kg_lb_js(ctx))


def _picker_ruler(ctx: Ctx, s: dict[str, Any], pk: dict[str, Any]) -> tuple[str, str]:
    lo, hi, step = pk.get("min", 0), pk.get("max", 100), pk.get("step", 1)
    n = int(round((hi - lo) / step))
    dflt = pk.get("default", lo)
    ranges = f'{{ u: {json.dumps(pk.get("unit", ""))}, min: {lo}, step: {step}, n: {n}, major: 10, mid: 5 }}'
    markup = _big_number(ctx, pk.get("label"), b("val"), b("unit")) + _ruler_markup(ctx)
    return markup, _ruler_js(ctx, ranges, str(int(round((dflt - lo) / step))), str(pk.get("reference", dflt)), "R.u")


def _picker_wheel(ctx: Ctx, s: dict[str, Any], pk: dict[str, Any]) -> tuple[str, str]:
    values = pk.get("values")
    if not values:
        fmt = pk.get("format", "{v}")
        step = pk.get("step", 1)
        values = [fmt.replace("{v}", str(v)) for v in range(pk["from"], pk["to"] + 1, step)]
    markup = (f'<div style="display: flex; gap: 14px; margin-top: 12px; animation: rise .5s both; animation-delay: .15s">'
              f'{_wheel(ctx, "w0", pk.get("label"))}</div>')
    js = _wheel_js(ctx) + (f"renderVals() {{\n  return {{ w0: this.wheel(\"w0\", {json.dumps([ctx.theme.text(v) for v in values])}, "
                           f"{int(pk.get('default', 0))}) }};\n}}")
    return markup, js


def _picker_birthdate(ctx: Ctx, s: dict[str, Any], pk: dict[str, Any]) -> tuple[str, str]:
    t = ctx.theme
    this_year = datetime.date.today().year
    y0, y1 = pk.get("from_year", 1940), pk.get("to_year", this_year - 13)
    dflt_year = pk.get("default_year", min(y1, 1995))
    markup = (f'<div style="display: flex; gap: 10px; margin-top: 12px; animation: rise .5s both; animation-delay: .15s">'
              f'{_wheel(ctx, "mo", None, 1.4)}{_wheel(ctx, "dy", None, 0.8)}{_wheel(ctx, "yr", None, 1)}</div>'
              f'<div style="align-self: center; display: flex; align-items: center; gap: 8px; padding: 10px 16px; border-radius: 999px; '
              f'background: {t.selected}; font-size: 15px; font-weight: 700; color: {t.accent_text}; animation: pop .5s both; animation-delay: .4s">'
              f'{icon("sparkle", 16, t.accent_text)}<span>{b("age")} years old</span></div>')
    js = _wheel_js(ctx) + f"""renderVals() {{
  var months = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  var days = [], years = [];
  for (var d = 1; d <= 31; d++) days.push(String(d));
  for (var y = {y0}; y <= {y1}; y++) years.push(String(y));
  var st = this.state || {{}};
  var yr = this.wheel("yr", years, {dflt_year - y0}), mo = this.wheel("mo", months, 5), dy = this.wheel("dy", days, 14);
  var year = {y0} + ((st.yr != null) ? st.yr : {dflt_year - y0});
  var month = (st.mo != null) ? st.mo : 5;
  var day = 1 + ((st.dy != null) ? st.dy : 14);
  var now = new Date(), age = now.getFullYear() - year;
  if (now.getMonth() < month || (now.getMonth() === month && now.getDate() < day)) age--;
  return {{ mo: mo, dy: dy, yr: yr, age: age }};
}}"""
    return markup, js


def _picker_height_weight(ctx: Ctx, s: dict[str, Any], pk: dict[str, Any]) -> tuple[str, str]:
    """Height + weight wheels. The unit toggle is kg · cm | lb · ft — weight always has kg/lb."""
    t = ctx.theme
    markup = (segmented(t, ("kg · cm", "met"), ("lb · ft", "imp"))
              + f'<sc-if value="{b("metric")}" hint-placeholder-val="{{{{ true }}}}"><div style="display: flex; gap: 14px; animation: rise .5s both; animation-delay: .2s">'
              + _wheel(ctx, "hm", "Height") + _wheel(ctx, "wm", "Weight") + '</div></sc-if>'
              + f'<sc-if value="{b("imperial")}" hint-placeholder-val="{{{{ false }}}}"><div style="display: flex; gap: 14px; animation: rise .5s both">'
              + _wheel(ctx, "hi", "Height") + _wheel(ctx, "wi", "Weight") + '</div></sc-if>')
    js = _wheel_js(ctx) + f"""renderVals() {{
  var self = this;
  var st = this.state || {{}};
  {segmented_js(t, "met", "imp", "unit", "imp")}
  var metric = st.unit !== "imp";
  var cm = [], kg = [], ft = [], lb = [];
  for (var c = 140; c <= 210; c++) cm.push(c + " cm");
  for (var k = 40; k <= 150; k++) kg.push(k + " kg");
  for (var f = 48; f <= 84; f++) ft.push(Math.floor(f / 12) + " ft " + (f % 12) + " in");
  for (var l = 90; l <= 330; l++) lb.push(l + " lb");
  var out = {{
    metric: metric, imperial: !metric,
    hm: this.wheel("hm", cm, 28), wm: this.wheel("wm", kg, 32), hi: this.wheel("hi", ft, 19), wi: this.wheel("wi", lb, 69),
    toMet: function () {{ self.setState({{ unit: "met" }}); }}, toImp: function () {{ self.setState({{ unit: "imp" }}); }}
  }};
  for (var sk in seg) out[sk] = seg[sk];
  return out;
}}"""
    return markup, js


def _picker_slider(ctx: Ctx, s: dict[str, Any], pk: dict[str, Any]) -> tuple[str, str]:
    """Range slider with zones (e.g. steady/balanced/fast). Weight-per-week sliders get the kg/lb toggle."""
    t = ctx.theme
    weight = is_weight_picker(pk)
    zones = pk.get("zones") or [{"label": "Low", "msg": ""}, {"label": "Medium", "msg": ""}, {"label": "High", "msg": ""}]
    rec = pk.get("recommended")
    lo, hi, step, dflt = pk.get("min", 1), pk.get("max", 10), pk.get("step", 1), pk.get("default", pk.get("min", 1))
    zone_icons = pk.get("zone_icons") or ["leaf", "target", "bolt"]
    animals = "".join(
        f'<div style="display: flex; flex-direction: column; align-items: center; gap: 6px; color: {b(f"a{i}.c")}; '
        f'transform: scale({b(f"a{i}.s")}); transition: all .35s cubic-bezier(.3,1.6,.5,1)">'
        f'<div style="animation: {b(f"a{i}.a")}">{icon(zone_icons[i % len(zone_icons)], 40, "currentColor", 2.2)}</div>'
        f'<span style="font-size: 13px; font-weight: 700; color: {t.muted}">{b(f"a{i}.lab")}</span></div>'
        for i in range(len(zones)))
    seg = segmented(t, ("kg", "kg"), ("lb", "lb"), width=72, center=True) if weight else ""
    markup = (seg + _big_number(ctx, pk.get("label"), b("v"), b("u"))
              + card(t, f'<div style="display: flex; justify-content: space-between; padding: 0 2px">{animals}</div>'
                        f'<input class="rng" type="range" min="{lo}" max="{hi}" step="{step}" value="{b("raw")}" onChange="{b("onV")}" '
                        f'aria-label="{t.text(s["title"])}" style="--p: {b("p")}%">'
                        f'<div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: 700; color: {t.muted}">'
                        f'<span>{b("minL")}</span><span>{b("maxL")}</span></div>', delay=0.22, pad="22px 20px", gap=18, radius=26)
              + f'<div style="display: flex; align-items: center; gap: 12px; padding: 14px 16px; border-radius: 18px; background: {b("msgBg")}; '
                f'transition: background .3s; animation: rise .5s both; animation-delay: .32s">'
                f'<sc-if value="{b("rec")}" hint-placeholder-val="{{{{ true }}}}"><span style="padding: 4px 10px; border-radius: 999px; '
                f'background: {t.success}; color: #FFFFFF; font-size: 12px; font-weight: 800; flex-shrink: 0">Recommended</span></sc-if>'
                f'<span style="font-size: 14px; line-height: 1.35; font-weight: 600">{b("msg")}</span></div>')
    unit = pk.get("unit", "")
    conv = "(st.unit === \"lb\" ? 2.2046 : 1)" if weight else "1"
    ulabel = ('(st.unit === "lb" ? "lb" : "kg") + ' + json.dumps(unit.replace("kg", "", 1))) if weight else json.dumps(unit)
    bgs = [t.line, t.success_fill, t.selected]
    js = f"""renderVals() {{
  var self = this;
  var st = this.state || {{}};
  {_kg_lb_js(ctx) if weight else ""}
  var raw = st.raw != null ? st.raw : {dflt};
  var k = {conv}, dec = {1 if (weight or step < 1) else 0};
  var Z = {json.dumps([{"label": t.text(z.get("label", "")), "msg": t.text(z.get("msg", ""))} for z in zones])};
  var zone = Math.min(Z.length - 1, Math.floor((raw - {lo}) / (({hi} - {lo}) / Z.length + 1e-9)));
  var bgs = {json.dumps(bgs)};
  var out = {{
    raw: raw, v: {"(raw * k).toFixed(dec)" if (weight or unit) else "Z[zone].label"}, u: {ulabel}, p: ((raw - {lo}) / ({hi} - {lo}) * 100).toFixed(1),
    minL: ({lo} * k).toFixed(dec), maxL: ({hi} * k).toFixed(dec),
    rec: zone === {json.dumps(rec)}, msg: Z[zone].msg, msgBg: bgs[zone % bgs.length],
    onV: function (e) {{ self.setState({{ raw: Number(e.target.value) }}); }}
  }};
  for (var i = 0; i < Z.length; i++) out["a" + i] = {{ c: i === zone ? "{t.accent}" : "{t.faint}", s: i === zone ? 1.18 : 0.92,
    a: i === zone ? "bob 1.2s ease-in-out infinite" : "none", lab: Z[i].label }};
  {_KG_LB_OUT if weight else ""}
  return out;
}}"""
    return markup, js


_PICKERS: dict[str, Callable[[Ctx, dict, dict], tuple[str, str]]] = {
    "weight": _picker_weight, "ruler": _picker_ruler, "wheel": _picker_wheel, "birthdate": _picker_birthdate,
    "height_weight": _picker_height_weight, "slider": _picker_slider,
}


def picker(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    t = ctx.theme
    pk = dict(s["picker"])
    kind = pk["type"]
    if kind == "ruler" and is_weight_picker(pk):
        kind = "weight"
    markup, js = _PICKERS[kind](ctx, s, pk)
    body = (header(t, nav["prev"], nav["frac"], nav["prev_frac"])
            + content(titles(t, s["title"], s.get("subtitle"), s.get("key")) + markup, gap=14 if kind in ("weight", "ruler") else 20)
            + cta(t, nav["next"], s.get("cta", "Continue"), key=s.get("key")))
    return page(t, s["title"], body, js)


# ------------------------------------------------------------ info / emotional

def _line_compare(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    a, b_ = (s.get("series") or ["With {app}", "On your own"])[:2]
    return card(t,
                f'<span style="font-size: 15px; font-weight: 700">{t.text(s.get("chart_label", "Your progress"))}</span>'
                f'<div style="position: relative; height: 190px"><svg width="302" height="190" viewBox="0 0 302 190" aria-hidden="true" style="overflow: visible">'
                f'<line x1="0" y1="40" x2="302" y2="40" stroke="{t.line}" stroke-width="1.5" stroke-dasharray="4 6"></line>'
                f'<line x1="0" y1="100" x2="302" y2="100" stroke="{t.line}" stroke-width="1.5" stroke-dasharray="4 6"></line>'
                f'<line x1="0" y1="160" x2="302" y2="160" stroke="{t.faint}" stroke-width="1.5"></line>'
                f'<path d="M8 150 C60 146 80 70 130 68 C180 66 200 140 294 146" stroke="{t.faint}" stroke-width="4" fill="none" stroke-linecap="round" '
                f'stroke-dasharray="700" style="animation: draw 1.6s cubic-bezier(.4,0,.2,1) both; animation-delay: .4s"></path>'
                f'<path d="M8 150 C70 144 90 80 150 62 C200 48 240 40 294 38" stroke="{t.accent}" stroke-width="5" fill="none" stroke-linecap="round" '
                f'stroke-dasharray="700" style="animation: draw 1.6s cubic-bezier(.4,0,.2,1) both; animation-delay: .7s"></path>'
                f'<circle cx="8" cy="150" r="6" fill="{t.surface}" stroke="{t.ink}" stroke-width="3"></circle></svg>'
                f'<div style="position: absolute; right: -10px; top: -8px; animation: pop .5s cubic-bezier(.2,.8,.2,1) both; animation-delay: 2.1s">'
                f'{mascot(ctx, s.get("mascot", "cheer"), 52, "bob 2s ease-in-out infinite")}</div></div>'
                f'<div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; color: {t.muted}"><span>Month 1</span><span>Month 6</span></div>'
                f'<div style="display: flex; gap: 16px; font-size: 13px; font-weight: 700">'
                f'<span style="display: flex; align-items: center; gap: 6px"><span style="width: 18px; height: 5px; border-radius: 3px; background: {t.accent}"></span>{t.text(a)}</span>'
                f'<span style="display: flex; align-items: center; gap: 6px"><span style="width: 18px; height: 5px; border-radius: 3px; background: {t.faint}"></span>{t.text(b_)}</span></div>')


def _bars_compare(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    a, b_ = (s.get("series") or ["On your own", "With {app}"])[:2]
    return card(t,
                f'<div style="display: flex; align-items: flex-end; justify-content: center; gap: 28px; height: 260px">'
                f'<div style="display: flex; flex-direction: column; align-items: center; gap: 10px; width: 110px">'
                f'<span style="font-size: 14px; font-weight: 700; color: {t.muted}">{t.text(a)}</span>'
                f'<div style="width: 100%; height: 80px; border-radius: 18px 18px 8px 8px; background: {t.line}; transform-origin: bottom; '
                f'animation: growY .9s cubic-bezier(.2,.8,.2,1) both; animation-delay: .4s"></div></div>'
                f'<div style="display: flex; flex-direction: column; align-items: center; gap: 10px; width: 110px">'
                f'<div style="animation: pop .5s both; animation-delay: 1.3s">{mascot(ctx, s.get("mascot", "cheer"), 70, "bob 1.8s ease-in-out infinite")}</div>'
                f'<div style="width: 100%; height: 160px; border-radius: 18px 18px 8px 8px; background: linear-gradient(180deg, {t.glow}, {t.accent}); '
                f'transform-origin: bottom; animation: growY 1s cubic-bezier(.2,.8,.2,1) both; animation-delay: .6s; display: flex; align-items: flex-start; '
                f'justify-content: center; padding: 14px 6px 0; box-sizing: border-box; text-align: center">'
                f'<span style="color: #FFFFFF; font-size: 15px; font-weight: 800">{t.text(b_)}</span></div></div></div>',
                pad="26px 24px 22px", gap=18)


def _growth_curve(ctx: Ctx, s: dict[str, Any]) -> str:
    t = ctx.theme
    ms = (s.get("milestones") or ["Today", "3 days", "7 days", "30 days"])[:4]
    dots = "".join(f'<div style="position: absolute; left: {x - 9}px; top: {y - 9}px; width: 18px; height: 18px; border-radius: 9px; '
                   f'background: {t.surface}; border: 4px solid {c}; box-sizing: border-box; animation: pop .45s both; animation-delay: {d:.2f}s"></div>'
                   for x, y, c, d in [(10, 176, t.ink, 0.5), (120, 136, t.accent, 1.0), (205, 78, t.accent, 1.4), (292, 26, t.success, 1.8)])
    return card(t,
                f'<span style="font-size: 15px; font-weight: 700">{t.text(s.get("chart_label", "Your progress"))}</span>'
                f'<div style="position: relative; height: 200px"><svg width="302" height="200" viewBox="0 0 302 200" aria-hidden="true" style="overflow: visible">'
                f'<defs><linearGradient id="pg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t.accent}" stop-opacity=".28"></stop>'
                f'<stop offset="1" stop-color="{t.accent}" stop-opacity="0"></stop></linearGradient></defs>'
                f'<path d="M10 176 C60 172 90 160 120 136 C170 96 220 44 292 26 L292 190 L10 190 Z" fill="url(#pg)" style="animation: fadein 1s both; animation-delay: 1.3s"></path>'
                f'<path d="M10 176 C60 172 90 160 120 136 C170 96 220 44 292 26" stroke="{t.accent}" stroke-width="5" fill="none" stroke-linecap="round" '
                f'stroke-dasharray="700" style="animation: draw 1.6s cubic-bezier(.4,0,.2,1) both; animation-delay: .4s"></path>'
                f'<line x1="10" y1="190" x2="292" y2="190" stroke="{t.faint}" stroke-width="1.5"></line></svg>{dots}'
                f'<div style="position: absolute; right: -6px; top: -44px; animation: pop .5s both; animation-delay: 2s">'
                f'{mascot(ctx, s.get("mascot", "trophy"), 54, "bob 1.8s ease-in-out infinite")}</div></div>'
                f'<div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: 700; color: {t.muted}; padding: 0 2px">'
                + "".join(f"<span>{t.text(m)}</span>" for m in ms) + "</div>", pad="22px 20px 20px")


def info(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    t = ctx.theme
    visual = {"line_compare": _line_compare, "bars_compare": _bars_compare, "growth_curve": _growth_curve}[s["visual"]](ctx, s)
    foot = (f'<p{l10n(s.get("key"), "footnote")} style="margin: 0; font-size: 16px; line-height: 1.45; color: {t.muted}; text-align: center; '
            f'animation: rise .5s both; animation-delay: .5s">{t.text(s["footnote"])}</p>') if s.get("footnote") else ""
    body = (header(t, nav["prev"], nav["frac"], nav["prev_frac"])
            + content(titles(t, s["title"], s.get("subtitle"), s.get("key")) + visual + foot)
            + cta(t, nav["next"], s.get("cta", "Continue"), key=s.get("key")))
    return page(t, s["title"], body)


def _hero(ctx: Ctx, s: dict[str, Any], default_state: str, size: int = 160, decor: str = "") -> str:
    t = ctx.theme
    return (f'<div style="position: relative; width: 200px; height: 200px; display: flex; align-items: center; justify-content: center">{decor}'
            f'<div style="position: absolute; width: 170px; height: 170px; border-radius: 50%; background: {t.selected}"></div>'
            f'<div style="position: relative; animation: pop .7s cubic-bezier(.2,.8,.2,1) both">{mascot(ctx, s.get("mascot", default_state), size)}</div></div>')


def emotional(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    t = ctx.theme
    decor = pulse_rings(t) if "heart" not in s.get("motion", "") else floating_hearts(t)
    inner = (f'<div style="flex-grow: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 34px; padding: 0 28px">'
             + _hero(ctx, s, "cheer", decor=decor)
             + titles(t, s["title"], s.get("subtitle"), s.get("key"), delay=0.35, center=True, size=34) + "</div>")
    body = header(t, nav["prev"], nav["frac"], nav["prev_frac"]) + inner + cta(t, nav["next"], s.get("cta", "Continue"), key=s.get("key"))
    return page(t, s["title"], body)


def trust(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    """Privacy promise + (when the spec needs consent) an explicit consent checkbox that gates the CTA."""
    t = ctx.theme
    key = s.get("key")
    consent = s.get("consent", bool((ctx.spec.get("consent") or {}).get("health")))
    consent_text = s.get("consent_text") or ("I agree that {app} processes my answers to create my plan, "
                                             "as described in the Privacy Policy.")
    box = (f'<button type="button" onClick="{b("toggle")}" role="checkbox" aria-checked="{b("on")}" style="display: flex; gap: 12px; '
           f'align-items: flex-start; padding: 14px 16px; border-radius: 18px; border: 2px solid {b("bd")}; background: {b("bg")}; text-align: left; '
           f'cursor: pointer; transition: all .25s; animation: rise .6s both; animation-delay: .55s">'
           f'<span style="width: 24px; height: 24px; border-radius: 7px; box-sizing: border-box; border: 2px solid {b("cbd")}; background: {b("cb")}; '
           f'display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: all .25s">'
           f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round" '
           f'aria-hidden="true" style="opacity: {b("co")}; transform: scale({b("co")})">{ICONS["check"]}</svg></span>'
           f'<span{l10n(key, "consent")} style="font-size: 13px; line-height: 1.4; font-weight: 600">{t.text(consent_text)}</span></button>') if consent else ""
    inner = (f'<div style="flex-grow: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 18px; padding: 0 24px">'
             f'<div style="position: relative; width: 160px; height: 160px; display: flex; align-items: center; justify-content: center">'
             f'<div style="position: absolute; inset: 0; border-radius: 50%; background: {t.selected}; animation: pop .6s both"></div>{floating_hearts(t)}'
             f'<div style="position: relative; animation: pop .7s cubic-bezier(.2,.8,.2,1) both; animation-delay: .15s">{mascot(ctx, s.get("mascot", "love"), 136)}</div></div>'
             + titles(t, s["title"], s.get("subtitle"), key, delay=0.3, center=True, size=34)
             + f'<div style="display: flex; gap: 14px; align-items: flex-start; padding: 18px; border-radius: 22px; background: {t.surface}; '
               f'border: 1.5px solid {t.line}; animation: rise .6s both; animation-delay: .45s">'
               f'<span style="width: 40px; height: 40px; border-radius: 20px; background: {t.success_fill}; display: flex; align-items: center; '
               f'justify-content: center; flex-shrink: 0">{icon("lock", 20, t.success_text)}</span>'
               f'<span style="display: flex; flex-direction: column; gap: 4px"><strong style="font-size: 15px">Your privacy and security matter to us.</strong>'
               f'<span{l10n(key, "privacy")} style="font-size: 14px; line-height: 1.4; color: {t.muted}">{t.text(s.get("privacy", ""))}</span></span></div>'
             + box + "</div>")
    js = (f"""renderVals() {{
  var self = this;
  var on = !!(this.state && this.state.ok);
  return {{
    on: on ? "true" : "false", bd: on ? "{t.accent}" : "{t.line}", bg: on ? "{t.selected}" : "{t.surface}",
    cb: on ? "{t.accent}" : "transparent", cbd: on ? "{t.accent}" : "{t.faint}", co: on ? 1 : 0,
    ctaBg: on ? "{t.cta}" : "{t.cta_disabled}",
    toggle: function () {{ self.setState({{ ok: !on }}); }}
  }};
}}""" if consent else f'renderVals() {{ return {{ ctaBg: "{t.cta}" }}; }}')
    body = header(t, nav["prev"], nav["frac"], nav["prev_frac"]) + inner + cta(t, nav["next"], s.get("cta", "Continue"), bg=b("ctaBg"), key=key)
    return page(t, s["title"], body, js)


def permission(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    t = ctx.theme
    perm = s.get("permission") or {}

    def tile(inner: str, bg: str, d: float) -> str:
        return (f'<div style="width: 92px; height: 92px; border-radius: 26px; background: {bg}; display: flex; align-items: center; '
                f'justify-content: center; box-shadow: 0 14px 30px {rgba(t.ink, .12)}; animation: pop .6s both; animation-delay: {d:.2f}s">{inner}</div>')
    sync = "".join(f'<span style="width: 8px; height: 8px; border-radius: 4px; background: {t.accent}; animation: dot 1.2s ease-in-out infinite; '
                   f'animation-delay: {i * 0.2:.1f}s"></span>' for i in range(4))
    rows = "".join(f'<div style="display: flex; align-items: center; gap: 14px; padding: 14px 16px; border-radius: 18px; background: {t.surface}; '
                   f'border: 1.5px solid {t.line}; animation: rise .5s both; animation-delay: {0.35 + i * 0.07:.2f}s">'
                   f'<span style="font-size: 16px; font-weight: 700; flex-grow: 1">{t.text(r)}</span>{icon("check", 20, t.success, 2.6)}</div>'
                   for i, r in enumerate(s.get("rows") or []))
    visual = (f'<div style="display: flex; align-items: center; justify-content: center; gap: 16px; margin: 10px 0 4px">'
              + tile(app_mark(ctx, 92), t.selected, 0.1) + f'<div style="display: flex; gap: 6px">{sync}</div>'
              + tile(icon(perm.get("icon", "camera2"), 46, t.accent_text, 2), t.surface, 0.25) + "</div>"
              + f'<div style="display: flex; flex-direction: column; gap: 10px">{rows}</div>')
    skip = (f'<a href="{nav["next"]}" style="display: flex; align-items: center; justify-content: center; height: 44px; font-size: 15px; '
            f'font-weight: 700; color: {t.muted}">Not now</a>') if s.get("optional", True) else ""
    body = (header(t, nav["prev"], nav["frac"], nav["prev_frac"])
            + content(titles(t, s["title"], s.get("subtitle"), s.get("key")) + visual, gap=22)
            + cta(t, nav["next"], s.get("cta", "Continue"), extra=skip, key=s.get("key")))
    return page(t, s["title"], body)


def preferences(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    t = ctx.theme
    toggles = s.get("toggles") or []
    rows = "".join(
        f'<div style="display: flex; gap: 14px; align-items: flex-start; padding: 20px; border-radius: 24px; background: {t.surface}; '
        f'box-shadow: 0 10px 28px {rgba(t.ink, .06)}; animation: rise .5s both; animation-delay: {0.15 + i * 0.1:.2f}s">'
        f'<span style="display: flex; flex-direction: column; gap: 4px; flex-grow: 1"><strong{l10n(s.get("key"), f"toggle{i}")} style="font-size: 16px; line-height: 1.3">{t.text(tg["title"])}</strong>'
        f'<span style="font-size: 14px; line-height: 1.4; color: {t.muted}">{t.text(tg.get("sub", ""))}</span></span>'
        f'<button type="button" role="switch" aria-checked="{b(f"p{i}.on")}" aria-label="{t.text(tg["title"])}" onClick="{b(f"p{i}.tog")}" '
        f'style="width: 56px; height: 34px; border-radius: 17px; border: none; padding: 3px; background: {b(f"p{i}.bg")}; cursor: pointer; '
        f'flex-shrink: 0; transition: background .25s; display: flex"><span style="width: 28px; height: 28px; border-radius: 14px; background: #FFFFFF; '
        f'box-shadow: 0 2px 6px {rgba(t.ink, .25)}; transform: translateX({b(f"p{i}.x")}px); transition: transform .3s cubic-bezier(.3,1.5,.5,1)"></span></button></div>'
        for i, tg in enumerate(toggles))
    defaults = json.dumps([bool(tg.get("default", False)) for tg in toggles])
    js = f"""renderVals() {{
  var self = this;
  var st = this.state || {{}};
  var DEF = {defaults}, out = {{}};
  DEF.forEach(function (def, i) {{
    var k = "p" + i, on = st[k] != null ? st[k] : def;
    out[k] = {{ on: on ? "true" : "false", bg: on ? "{t.success}" : "{t.faint}", x: on ? 22 : 0,
      tog: function () {{ var o = {{}}; o[k] = !on; self.setState(o); }} }};
  }});
  return out;
}}"""
    body = (header(t, nav["prev"], nav["frac"], nav["prev_frac"])
            + content(titles(t, s["title"], s.get("subtitle"), s.get("key")) + rows, gap=18)
            + cta(t, nav["next"], s.get("cta", "Continue"), key=s.get("key")))
    return page(t, s["title"], body, js)


def loading(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    t = ctx.theme
    items = (s.get("items") or ["Your profile", "Your plan"])[:6]
    statuses = s.get("statuses") or ["Working…", "Your plan is ready"]
    n = len(items)
    chk = "".join(
        f'<div style="display: flex; align-items: center; gap: 12px; font-size: 16px; font-weight: 600; animation: rise .4s both; animation-delay: {0.1 + i * 0.05:.2f}s">'
        f'<span style="width: 8px; height: 8px; border-radius: 4px; background: {t.faint}; flex-shrink: 0"></span><span style="flex-grow: 1">{t.text(it)}</span>'
        f'<span style="width: 26px; height: 26px; border-radius: 13px; background: {b(f"c{i}.bg")}; display: flex; align-items: center; justify-content: center; '
        f'transform: scale({b(f"c{i}.s")}); transition: all .35s cubic-bezier(.3,1.6,.5,1)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
        f'stroke="#FFFFFF" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="opacity: {b(f"c{i}.o")}">{ICONS["check"]}</svg></span></div>'
        for i, it in enumerate(items))
    grad = ", ".join([t.accent] + t.series[1:3])
    body = (f'<div style="flex-grow: 1; display: flex; flex-direction: column; gap: 24px; padding: 56px 24px 0">'
            f'<div style="display: flex; flex-direction: column; align-items: center; gap: 12px; text-align: center">'
            f'{mascot(ctx, s.get("mascot", "think"), 96, "bob 2.2s ease-in-out infinite")}'
            f'<span style="font-family: {t.display_css}; font-size: 76px; font-weight: 800; letter-spacing: -0.05em; line-height: 1; '
            f'font-variant-numeric: tabular-nums">{b("pct")}%</span>'
            f'<h1{l10n(s.get("key"), "title")} style="margin: 0; font-family: {t.display_css}; font-size: 28px; line-height: 1.12; font-weight: 800; '
            f'letter-spacing: -0.02em; text-wrap: balance">{t.text(s["title"])}</h1></div>'
            f'<div style="display: flex; flex-direction: column; gap: 10px"><div style="height: 10px; border-radius: 5px; background: {t.line}; overflow: hidden">'
            f'<div style="width: {b("pct")}%; height: 100%; border-radius: 5px; background: linear-gradient(90deg, {grad}); transition: width .12s linear"></div></div>'
            f'<span style="text-align: center; font-size: 14px; font-weight: 600; color: {t.muted}">{b("status")}</span></div>'
            + card(t, f'<span style="font-size: 16px; font-weight: 800">{t.text(s.get("card_title", "Preparing"))}</span>' + chk,
                   delay=0.1, pad="22px", gap=16, radius=26)
            + f'</div><div style="padding: 12px 24px 34px; height: 104px; box-sizing: border-box">'
              f'<sc-if value="{b("done")}" hint-placeholder-val="{{{{ false }}}}"><a href="{nav["next"]}" style="display: flex; align-items: center; '
              f'justify-content: center; height: 58px; border-radius: 29px; background: {t.cta}; color: #FFFFFF; font-size: 19px; font-weight: 800; '
              f'box-shadow: 0 12px 26px {t.cta_shadow}; animation: pop .45s both">{t.text(s.get("cta", "Continue"))}</a></sc-if></div>')
    js = f"""componentDidMount() {{
  var self = this;
  this._t = setInterval(function () {{
    var p = (self.state && self.state.pct) || 0;
    if (p >= 100) {{ clearInterval(self._t); return; }}
    self.setState({{ pct: Math.min(100, p + (p < 60 ? 2 : 1)) }});
  }}, 70);
}}
componentWillUnmount() {{ clearInterval(this._t); }}
renderVals() {{
  var pct = (this.state && this.state.pct) || 0;
  var S = {json.dumps([t.text(x) for x in statuses])};
  var status = pct >= 100 ? S[S.length - 1] : S[Math.min(S.length - 2, Math.floor(pct / (100 / Math.max(1, S.length - 1))))];
  function c(th) {{ var on = pct >= th; return {{ bg: on ? "{t.success}" : "{t.line}", s: on ? 1 : 0.85, o: on ? 1 : 0 }}; }}
  var out = {{ pct: pct, status: status, done: pct >= 100 }};
  for (var i = 0; i < {n}; i++) out["c" + i] = c(Math.round((i + 1) * 100 / {n}));
  return out;
}}"""
    return page(t, s["title"], body, js)


def plan_ready(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    t = ctx.theme
    cols = [t.ink, t.series[1 % len(t.series)], t.accent, t.series[2 % len(t.series)]]

    def ring(m: dict[str, Any], i: int) -> str:
        c = 2 * 3.14159 * 30
        d = 0.4 + i * 0.08
        return (f'<div style="display: flex; flex-direction: column; gap: 12px; padding: 16px; border-radius: 22px; background: {t.surface}; '
                f'box-shadow: 0 10px 26px {rgba(t.ink, .06)}; animation: rise .5s both; animation-delay: {d:.2f}s">'
                f'<div style="display: flex; align-items: center; justify-content: space-between"><span style="font-size: 14px; font-weight: 700">{t.text(m["label"])}</span>'
                f'<button type="button" aria-label="Edit {t.text(m["label"])}" style="width: 30px; height: 30px; border-radius: 15px; border: none; '
                f'background: {t.line}; display: flex; align-items: center; justify-content: center; cursor: pointer">{icon("pencil", 14, t.muted, 2)}</button></div>'
                f'<div style="position: relative; width: 76px; height: 76px; align-self: center"><svg width="76" height="76" viewBox="0 0 76 76" aria-hidden="true" '
                f'style="transform: rotate(-90deg)"><circle cx="38" cy="38" r="30" fill="none" stroke="{t.line}" stroke-width="8"></circle>'
                f'<circle cx="38" cy="38" r="30" fill="none" stroke="{cols[i % 4]}" stroke-width="8" stroke-linecap="round" stroke-dasharray="{c:.1f}" '
                f'style="--c: {c:.1f}; stroke-dashoffset: {c * (1 - float(m.get("frac", 0.7))):.1f}; animation: ring 1.3s cubic-bezier(.3,.9,.3,1) both; '
                f'animation-delay: {d + 0.3:.2f}s"></circle></svg><div style="position: absolute; inset: 0; display: flex; flex-direction: column; '
                f'align-items: center; justify-content: center"><span style="font-size: 18px; font-weight: 800; font-variant-numeric: tabular-nums">{t.text(str(m["value"]))}</span>'
                f'<span style="font-size: 11px; font-weight: 700; color: {t.muted}">{t.text(m.get("unit", ""))}</span></div></div></div>')
    metrics = "".join(ring(m, i) for i, m in enumerate((s.get("metrics") or [])[:4]))
    score = s.get("score")
    score_row = (f'<div style="display: flex; align-items: center; gap: 12px; padding: 14px 16px; border-radius: 20px; background: {t.surface}; '
                 f'box-shadow: 0 10px 26px {rgba(t.ink, .06)}; animation: rise .5s both; animation-delay: .72s">'
                 f'<span style="width: 36px; height: 36px; border-radius: 18px; background: {t.selected}; display: flex; align-items: center; '
                 f'justify-content: center; flex-shrink: 0">{icon("heart", 18, t.accent_text, 2.2)}</span>'
                 f'<span style="display: flex; flex-direction: column; gap: 6px; flex-grow: 1"><span style="display: flex; justify-content: space-between; '
                 f'font-size: 14px; font-weight: 700"><span>{t.text(s.get("score_label", "Score"))}</span><span>{score}/10</span></span>'
                 f'<span style="height: 6px; border-radius: 3px; background: {t.line}; overflow: hidden; display: block"><span style="display: block; '
                 f'width: {int(score) * 10}%; height: 100%; border-radius: 3px; background: {t.success}; transform-origin: left; animation: barIn 1s both; '
                 f'animation-delay: 1s; --from: 0"></span></span></span></div>') if score is not None else ""
    body = (sparkle_confetti(t)
            + f'<div style="flex-grow: 1; display: flex; flex-direction: column; gap: 18px; padding: 64px 24px 0; position: relative">'
              f'<div style="display: flex; flex-direction: column; align-items: center; gap: 12px; text-align: center">'
              f'<div style="width: 56px; height: 56px; border-radius: 28px; background: {t.success}; display: flex; align-items: center; justify-content: center; '
              f'box-shadow: 0 10px 24px {rgba(t.success, .35)}; animation: pop .6s cubic-bezier(.2,.8,.2,1) both">{icon("check", 30, "#FFFFFF", 3)}</div>'
            + titles(t, s["title"], None, s.get("key"), delay=0.15, center=True, size=30)
            + f'<div style="display: flex; flex-direction: column; align-items: center; gap: 6px; animation: rise .5s both; animation-delay: .25s">'
              f'<span style="font-size: 15px; font-weight: 600; color: {t.muted}">{t.text(s.get("result_label", ""))}</span>'
              f'<span{l10n(s.get("key"), "result")} style="padding: 8px 16px; border-radius: 999px; background: {t.surface}; border: 1.5px solid {t.line}; '
              f'font-size: 16px; font-weight: 800">{t.text(s.get("result", ""))}</span></div></div>'
              f'<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px">{metrics}</div>{score_row}</div>'
            + cta(t, nav["next"], s.get("cta", "Continue"), key=s.get("key")))
    return page(t, s["title"], body)


def account(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    t = ctx.theme
    apple = ('<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M16.4 12.6c0-2.3 1.9-3.4 2-3.5-1.1-1.6-2.8-1.8-3.4-1.8-1.4-.1-2.8.9-3.5.9s-1.8-.9-3-.8C6.9 7.4 5.4 8.3 4.6 9.8c-1.7 2.9-.4 7.2 1.2 9.6.8 1.2 1.7 2.5 3 2.4 1.2 0 1.6-.8 3.1-.8s1.8.8 3.1.8 2.1-1.2 2.9-2.4c.9-1.3 1.3-2.6 1.3-2.7 0 0-2.8-1.1-2.8-4.1zM14.2 5.6c.6-.8 1.1-1.9 1-3-1 0-2.1.7-2.8 1.4-.6.7-1.2 1.8-1 2.9 1.1.1 2.1-.5 2.8-1.3z" fill="#FFFFFF"></path></svg>')
    body = (f'<div style="flex-grow: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 26px; padding: 0 24px; text-align: center">'
            f'<div style="position: relative; width: 170px; height: 170px; display: flex; align-items: center; justify-content: center">'
            f'<div style="position: absolute; inset: 0; border-radius: 50%; background: {t.selected}"></div>'
            f'<div style="position: relative; animation: pop .7s both">{mascot(ctx, s.get("mascot", "idle"), 150)}</div></div>'
            + titles(t, s["title"], s.get("subtitle"), s.get("key"), delay=0.2, center=True, size=34) + "</div>"
            f'<div style="padding: 12px 24px 34px; display: flex; flex-direction: column; gap: 12px; animation: rise .5s both; animation-delay: .3s">'
            f'<button type="button" style="display: flex; align-items: center; justify-content: center; gap: 10px; height: 58px; border-radius: 29px; '
            f'border: none; background: {t.ink}; color: #FFFFFF; font-size: 17px; font-weight: 700; cursor: pointer">{apple}Continue with Apple</button>'
            f'<button type="button" style="display: flex; align-items: center; justify-content: center; gap: 10px; height: 58px; border-radius: 29px; '
            f'border: 1.5px solid {t.faint}; background: {t.surface}; font-size: 17px; font-weight: 700; cursor: pointer"><span style="font-family: {t.display_css}; '
            f'font-size: 20px; font-weight: 800; color: #2F80ED">G</span>Continue with Google</button>'
            f'<a href="{nav["next"]}" style="display: flex; align-items: center; justify-content: center; height: 44px; font-size: 15px; font-weight: 700; '
            f'color: {t.muted}">Skip for now</a></div>')
    return page(t, s["title"], body)


# ------------------------------------------------------------ paywalls

def _plan_tile(t, k: str, p: dict[str, Any], d: float) -> str:
    return (f'<button type="button" onClick="{b(k + ".pick")}" aria-pressed="{b(k + ".on")}" style="position: relative; display: flex; flex-direction: column; '
            f'align-items: flex-start; gap: 2px; min-width: 0; padding: 16px 14px 14px; border-radius: 20px; border: 2.5px solid {b(k + ".bd")}; '
            f'background: {b(k + ".bg")}; text-align: left; cursor: pointer; transform: scale({b(k + ".sc")}); transition: all .3s cubic-bezier(.3,1.5,.5,1); '
            f'animation: rise .45s both; animation-delay: {d:.2f}s">'
            f'<sc-if value="{b(k + ".badge")}" hint-placeholder-val="{{{{ false }}}}"><span style="position: absolute; top: -13px; left: 50%; '
            f'transform: translateX(-50%); padding: 4px 12px; border-radius: 999px; background: {t.cta}; color: #FFFFFF; font-size: 12px; font-weight: 800; '
            f'letter-spacing: .04em; white-space: nowrap; box-shadow: 0 6px 14px {t.cta_shadow}">{b(k + ".badgeText")}</span></sc-if>'
            f'<span style="display: flex; align-items: center; justify-content: space-between; align-self: stretch"><span style="font-size: 14px; font-weight: 700; '
            f'color: {t.muted}">{p["name"]}</span><span style="width: 22px; height: 22px; border-radius: 11px; box-sizing: border-box; border: 2px solid {b(k + ".bd")}; '
            f'background: {b(k + ".rb")}; display: flex; align-items: center; justify-content: center; transition: all .25s"><svg width="12" height="12" '
            f'viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
            f'style="opacity: {b(k + ".dot")}">{ICONS["check"]}</svg></span></span>'
            f'<span style="font-family: {t.display_css}; font-size: 23px; font-weight: 800; letter-spacing: -0.02em">{p["price"]}</span>'
            f'<span style="font-size: 13px; font-weight: 700; color: {b(k + ".subC")}">{b(k + ".sub")}</span></button>')


def _shine_button(t, label_binding: str) -> str:
    return (f'<button type="button" style="position: relative; overflow: hidden; height: 60px; border-radius: 30px; border: none; background: {t.cta}; '
            f'color: #FFFFFF; font-size: 19px; font-weight: 800; cursor: pointer; box-shadow: 0 12px 26px {t.cta_shadow}">'
            f'<span style="position: absolute; top: 0; bottom: 0; left: 0; width: 60px; background: linear-gradient(90deg, rgba(255,255,255,0), '
            f'rgba(255,255,255,.45), rgba(255,255,255,0)); animation: shine 3.2s ease-in-out infinite"></span>'
            f'<span style="position: relative">{label_binding}</span></button>')


def paywall(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    """Hard paywall. Plans, prices, trial and savings come from the spec products."""
    t = ctx.theme
    plans = pricing.plans(ctx.spec, "default")[:3]
    keys = [f"p{i}" for i in range(len(plans))]
    tiles = "".join(_plan_tile(t, k, p, 0.55 + i * 0.05) for i, (k, p) in enumerate(zip(keys, plans)))
    locked = s.get("locked") or ["Your plan"]
    rows = "".join(
        f'<div style="display: flex; align-items: center; justify-content: space-between; gap: 10px; animation: rise .4s both; animation-delay: {0.35 + i * 0.05:.2f}s">'
        f'<span style="font-size: 14px; font-weight: 700; white-space: nowrap">{t.text(lab)}</span>'
        f'<span style="position: relative; display: flex; align-items: center; justify-content: flex-end; width: {72 - (i % 3) * 10}px; height: 18px">'
        f'<span style="position: absolute; inset: 0; border-radius: 9px; background: {t.line}"></span>'
        f'<span style="position: relative; font-size: 13px; font-weight: 800; color: {t.muted}; filter: blur(4.5px); padding-right: 8px; user-select: none" '
        f'aria-hidden="true">••••</span></span></div>' for i, lab in enumerate(locked[:5]))
    body = (f'<div style="position: absolute; left: 0; right: 0; top: 0; height: 330px; background: linear-gradient(180deg, {t.glow} 0%, {rgba(t.bg, 0)} 100%)"></div>'
            f'<div style="position: absolute; top: 54px; right: 20px; z-index: 2; animation: fadein .4s both; animation-delay: 2.5s">'
            f'<a href="{nav["next"]}" aria-label="Close" style="width: 34px; height: 34px; border-radius: 17px; background: {rgba(t.ink, .06)}; display: flex; '
            f'align-items: center; justify-content: center">{icon("close", 15, t.muted, 2.4)}</a></div>'
            f'<div style="position: relative; flex-grow: 1; display: flex; flex-direction: column; gap: 16px; padding: 74px 24px 0">'
            + titles(t, s["title"], s.get("subtitle"), s.get("key"), delay=0, center=True, size=32)
            + card(t, f'<div style="display: flex; align-items: center; gap: 8px">{icon("lock", 16, t.ink, 2.2)}'
                      f'<span style="font-size: 15px; font-weight: 800; flex-grow: 1">{t.text(s.get("card_title", "Unlocks with Premium"))}</span>'
                      f'<span style="padding: 4px 10px; border-radius: 999px; background: {t.line}; font-size: 12px; font-weight: 800; color: {t.muted}">Locked</span></div>'
                      f'<div style="display: flex; gap: 14px; align-items: stretch"><div style="position: relative; width: 108px; flex-shrink: 0; border-radius: 18px; '
                      f'background: {t.selected}; display: flex; align-items: flex-end; justify-content: center; overflow: hidden; min-height: 130px">'
                      f'{mascot(ctx, s.get("mascot", "snap"), 104, "none", extra="margin-bottom: -8px")}</div>'
                      f'<div style="display: flex; flex-direction: column; justify-content: space-between; gap: 10px; flex-grow: 1; min-width: 0; padding: 4px 0">{rows}</div></div>',
                   delay=0.2, pad="16px", radius=24)
            + f'<div style="display: flex; flex-direction: column; align-items: center; animation: rise .5s both; animation-delay: .45s">'
              f'<strong style="font-family: {t.display_css}; font-size: 20px; font-weight: 800; letter-spacing: -0.02em">{t.text(s.get("proof", "Built from your answers"))}</strong>'
              f'<span style="font-size: 13px; font-weight: 600; color: {t.muted}">{t.text(s.get("proof_sub", ""))}</span></div></div>'
            + f'<div style="position: relative; padding: 8px 24px 24px; display: flex; flex-direction: column; gap: 12px">'
              f'<div style="display: grid; grid-template-columns: repeat({max(1, len(plans))}, minmax(0, 1fr)); gap: 12px; padding-top: 10px">{tiles}</div>'
              f'<span style="text-align: center; font-size: 13px; font-weight: 600; color: {t.muted}">{b("fine")}</span>'
            + _shine_button(t, b("ctaLabel"))
            + f'<div style="display: flex; justify-content: center; gap: 18px; font-size: 12px; font-weight: 600"><a href="#" style="color: {t.muted}">Terms of Use</a>'
              f'<a href="#" style="color: {t.muted}">Privacy Policy</a><a href="#" style="color: {t.muted}">Restore purchase</a></div></div>')
    pdata = [{"k": k, "name": p["name"], "price": p["price"], "unit": p["unit"], "trial": p["trial"], "badge": p.get("badge"),
              "perWeek": p["per_week_text"], "pre": bool(p.get("preselected"))} for k, p in zip(keys, plans)]
    js = f"""renderVals() {{
  var self = this;
  var trialOK = this.props.trial != null ? this.props.trial : true;  // RevenueCat intro eligibility in the app
  var P = {json.dumps(pdata)};
  var pre = P.filter(function (p) {{ return p.pre; }})[0] || P[P.length - 1];
  var sel = (this.state && this.state.p) || pre.k;
  var out = {{}}, cur = pre;
  P.forEach(function (p) {{
    var on = sel === p.k, trial = trialOK && p.trial;
    if (on) cur = p;
    out[p.k] = {{
      on: on ? "true" : "false", bd: on ? "{t.cta}" : "{t.line}", bg: on ? "{t.selected}" : "{t.surface}",
      rb: on ? "{t.cta}" : "transparent", dot: on ? 1 : 0, sc: on ? 1.03 : 1,
      badge: !!p.badge, badgeText: p.badge || "",
      sub: trial ? p.trial : (p.badge ? p.perWeek : "Billed " + p.name.toLowerCase()), subC: trial || p.badge ? "{t.accent_text}" : "{t.muted}",
      pick: function () {{ self.setState({{ p: p.k }}); }}
    }};
  }});
  var tr = trialOK && cur.trial;
  out.ctaLabel = tr ? "Start my free trial" : "Unlock my plan";
  out.fine = tr ? cur.trial + ", then " + cur.price + " / " + cur.unit + " · Cancel anytime" : "Billed " + cur.price + " / " + cur.unit + " · Cancel anytime";
  return out;
}}"""
    return page(t, s["title"], body, js, props={"trial": {"editor": "boolean", "default": True}})


def offer(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    """Offer paywall on the separate offer product, anchored to spec.offer_anchor."""
    t = ctx.theme
    o = pricing.offer(ctx.spec)
    if not o:
        raise ValueError("offer screen needs a product in the 'offer' offering (spec.subscription.products)")
    item = o["anchor_item"]
    reg = o["regular"]
    chk = "".join(
        f'<div style="display: flex; align-items: center; gap: 10px; animation: rise .4s both; animation-delay: {0.6 + i * 0.06:.2f}s">'
        f'<span style="width: 22px; height: 22px; border-radius: 11px; background: {t.success}; display: flex; align-items: center; justify-content: center; '
        f'flex-shrink: 0">{icon("check", 13, "#FFFFFF", 3.4)}</span><span style="font-size: 15px; font-weight: 600">{t.text(x)}</span></div>'
        for i, x in enumerate((s.get("benefits") or [])[:5]))
    anchor = (f'<div style="position: relative; animation: pop .6s cubic-bezier(.2,.8,.2,1) both; animation-delay: .3s">'
              f'<div style="width: 104px; height: 104px; border-radius: 28px; background: {t.surface}; box-shadow: 0 14px 30px {rgba(t.ink, .1)}; '
              f'display: flex; align-items: center; justify-content: center">{icon(item if item in ICONS else "gift", 54, t.accent_text, 1.8)}</div>'
              f'<span{l10n(o.get("anchor_key"), "badge") if o.get("anchor_key") else ""} style="position: absolute; right: -10px; top: -10px; padding: 4px 9px; '
              f'border-radius: 10px; background: {t.surface}; font-size: 12px; font-weight: 800; box-shadow: 0 6px 14px {rgba(t.ink, .1)}; transform: rotate(8deg); '
              f'white-space: nowrap">1 {t.text(item)} / month</span></div>')
    strike = f'<span style="text-decoration: line-through">{reg["price"]}</span> ' if reg else ""
    body = (f'<div style="position: absolute; top: 54px; left: 20px; right: 20px; display: flex; justify-content: space-between; align-items: center; z-index: 2">'
            f'<span style="padding: 6px 12px; border-radius: 999px; background: {t.ink}; color: {t.bg}; font-size: 12px; font-weight: 800; letter-spacing: .06em; '
            f'animation: pop .5s both">{t.text(s["title"]).upper()}</span>'
            f'<a href="{ctx.first_main}" aria-label="Close" style="width: 34px; height: 34px; border-radius: 17px; background: {rgba(t.ink, .06)}; display: flex; '
            f'align-items: center; justify-content: center; animation: fadein .4s both; animation-delay: 2s">{icon("close", 15, t.muted, 2.4)}</a></div>'
            f'<div style="flex-grow: 1; display: flex; flex-direction: column; align-items: center; gap: 22px; padding: 110px 24px 0; text-align: center">'
            f'<div style="display: flex; align-items: center; justify-content: center; gap: 18px"><div style="animation: pop .6s cubic-bezier(.2,.8,.2,1) both; '
            f'animation-delay: .1s">{app_mark(ctx, 104)}</div><span style="font-family: {t.display_css}; font-size: 48px; font-weight: 800; color: {t.accent_text}; '
            f'animation: pop .5s both; animation-delay: .45s">&lt;</span>{anchor}</div>'
            f'<div style="display: flex; flex-direction: column; gap: 4px; animation: rise .5s both; animation-delay: .5s">'
            f'<h1{l10n(s.get("key"), "headline")} style="margin: 0; font-family: {t.display_css}; font-size: 32px; line-height: 1.06; font-weight: 800; letter-spacing: -0.03em">'
            f'Less than one {t.text(item)} a month,<br><span style="color: {t.accent_text}">unlock everything</span></h1></div>'
            f'<div style="align-self: stretch; display: flex; flex-direction: column; gap: 12px; padding: 0 18px">{chk}</div></div>'
            f'<div style="padding: 12px 24px 26px; display: flex; flex-direction: column; gap: 12px">'
            f'<div style="position: relative; display: flex; align-items: center; gap: 14px; padding: 16px 18px; border-radius: 22px; border: 2.5px solid {t.cta}; '
            f'background: {t.selected}; animation: rise .45s both; animation-delay: .85s">'
            + (f'<span style="position: absolute; top: -12px; right: 16px; padding: 4px 10px; border-radius: 999px; background: {t.cta}; color: #FFFFFF; '
               f'font-size: 12px; font-weight: 800">{o["off"]}% OFF</span>' if o["off"] else "")
            + f'<span style="display: flex; flex-direction: column; gap: 2px; flex-grow: 1; text-align: left"><span style="font-size: 16px; font-weight: 800">{o["name"]}</span>'
              f'<span style="font-size: 14px; color: {t.muted}">{strike}{o["price"]} / {o["unit"]}</span></span>'
              f'<span style="display: flex; flex-direction: column; align-items: flex-end"><span style="font-family: {t.display_css}; font-size: 22px; font-weight: 800">'
              f'{o["per_month_text"]}</span><span style="font-size: 12px; font-weight: 700; color: {t.muted}">per month</span></span></div>'
            + _shine_button(t, "Claim my offer")
            + f'<span style="text-align: center; font-size: 12px; font-weight: 600; color: {t.muted}">Billed {o["price"]} / {o["unit"]} · Cancel anytime</span>'
              f'<a href="{ctx.first_main}" style="display: flex; align-items: center; justify-content: center; height: 36px; font-size: 15px; font-weight: 700; '
              f'color: {t.muted}">No thanks</a></div>')
    return page(t, s["title"], body)


def welcome(ctx: Ctx, s: dict[str, Any], nav: dict[str, Any]) -> str:
    t = ctx.theme
    chips = s.get("chips") or []
    spots = ["left: 18px; top: 36px", "right: 14px; top: 104px", "right: 20px; bottom: 104px", "left: 22px; bottom: 60px"]
    cols = [t.ink, t.accent] + t.series[1:]
    chip_html = "".join(
        f'<div style="position: absolute; {spots[i % 4]}; display: flex; align-items: center; gap: 8px; padding: 9px 14px; border-radius: 16px; '
        f'background: {t.surface}; box-shadow: 0 10px 24px {rgba(t.ink, .12)}; font-size: 14px; font-weight: 700; white-space: nowrap; '
        f'animation: pop .55s cubic-bezier(.2,.8,.2,1) both; animation-delay: {0.7 + i * 0.22:.2f}s"><span style="width: 10px; height: 10px; '
        f'border-radius: 5px; background: {cols[i % len(cols)]}"></span>{t.text(c)}</div>' for i, c in enumerate(chips[:4]))
    brackets = "".join(f'<div style="position: absolute; {p}; width: 34px; height: 34px; border-color: {t.accent}; border-style: solid; '
                       f'border-width: {bw}; border-radius: {br}"></div>'
                       for p, bw, br in [("left: 0; top: 0", "4px 0 0 4px", "14px 0 0 0"), ("right: 0; top: 0", "4px 4px 0 0", "0 14px 0 0"),
                                         ("left: 0; bottom: 0", "0 0 4px 4px", "0 0 0 14px"), ("right: 0; bottom: 0", "0 4px 4px 0", "0 0 14px 0")])
    body = (f'<div style="padding: 60px 24px 0; display: flex; align-items: center; gap: 10px; animation: fadein .6s both">{app_mark(ctx)}'
            f'<span style="font-family: {t.display_css}; font-size: 22px; font-weight: 800; letter-spacing: -0.02em">{t.text(t.display_name)}</span></div>'
            f'<div style="flex-grow: 1; position: relative; display: flex; align-items: center; justify-content: center">'
            f'<div style="position: absolute; width: 330px; height: 330px; border-radius: 50%; background: radial-gradient(circle, {t.glow} 0%, {rgba(t.glow, 0)} 70%)"></div>'
            f'<div style="position: relative; width: 250px; height: 250px; display: flex; align-items: center; justify-content: center; animation: pop .7s cubic-bezier(.2,.8,.2,1) both">'
            f'<div style="width: 210px; height: 210px; border-radius: 50%; background: {t.surface}; display: flex; align-items: center; justify-content: center; '
            f'box-shadow: 0 14px 36px {t.shadow}">{mascot(ctx, s.get("mascot", "wave"), 170, "bob 2.8s ease-in-out infinite")}</div>{brackets}'
            f'<div style="position: absolute; left: 10px; right: 10px; top: 36px; height: 3px; border-radius: 2px; background: {t.accent}; '
            f'box-shadow: 0 0 18px 4px {rgba(t.accent, .45)}; animation: scan 3.2s ease-in-out infinite"></div></div>{chip_html}</div>'
            f'<div style="padding: 0 24px; display: flex; flex-direction: column; gap: 12px; animation: rise .6s cubic-bezier(.2,.8,.2,1) both; animation-delay: .3s">'
            f'<h1{l10n(s.get("key"), "title")} style="margin: 0; font-family: {t.display_css}; font-size: 40px; line-height: 1.02; font-weight: 800; letter-spacing: -0.035em; '
            f'text-wrap: balance">{t.text(s["title"])}</h1>'
            f'<p{l10n(s.get("key"), "subtitle")} style="margin: 0; font-size: 17px; line-height: 1.45; color: {t.muted}">{t.text(s.get("subtitle", ""))}</p></div>'
            + cta(t, nav["next"], s.get("cta", "Get started"), key=s.get("key"),
                  extra=f'<button type="button" style="height: 44px; border: none; background: transparent; font-size: 15px; font-weight: 600; color: {t.muted}; '
                        f'cursor: pointer">I already have an account · <span style="color: {t.ink}; font-weight: 800">Sign in</span></button>'))
    return page(t, s["title"], body)


RENDERERS: dict[str, Callable[[Ctx, dict[str, Any], dict[str, Any]], str]] = {
    "welcome": welcome, "question": question, "picker": picker, "info": info, "emotional": emotional,
    "trust": trust, "permission": permission, "preferences": preferences, "loading": loading,
    "plan_ready": plan_ready, "account": account, "paywall": paywall, "offer": offer,
}
