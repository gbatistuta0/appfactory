"""Mascot motion boards (canvas page "mascot") — the motion spec MascotView.swift implements.

LESSON: never rig the character from a separately generated parts sheet — it
drifts off-model. Every state animates the founder-APPROVED pose PNG directly (whole-pose
transforms around the feet), and blinks swap in a closed-eye copy of the same pose made by
`mascot_blink`. Until poses exist, the boards show the token-tinted placeholder.
"""

from __future__ import annotations

import json

from .dc import Ctx, mascot_svg
from .theme import Theme

W, H = 360, 470
STAGE = 290  # rendered pose box; MascotView scales the same numbers from a 290 pt stage

# state -> (tag, usage context, motion note). Keep in sync with MascotView.swift.
STATES: dict[str, tuple[str, str, str]] = {
    "idle": ("Idle", "Home · Settings · waiting", "Breathe, soft sway, double blink"),
    "wave": ("Wave", "Welcome · Save progress · first day", "Rock and hop, blink, “Hi!” pop"),
    "cheer": ("Cheer", "Goal hit · plan ready · realistic target", "Jump with squash, wiggle, confetti"),
    "think": ("Think", "Analyzing · plan loading · text input tip", "Slow tilt, blink, thinking bubble"),
    "love": ("Love", "Trust screen · result saved · on target", "Heartbeat pulse, floating hearts"),
    "snap": ("Snap", "Capture intro · paywall plan card · empty state", "Shutter squash, flash, sparkles"),
    "trophy": ("Trophy", "Streak · milestone · potential chart", "Proud hop, trophy gleam, sparkles"),
    "sleep": ("Sleep", "Daily limit · night · empty states", "Eyes closed, slow breath, floating Zzz"),
}

MOTION = {
    "idle": """
.body{animation:breathe 3.2s ease-in-out infinite}
.pose{animation:sway 6.4s ease-in-out infinite}
.blink{animation:dblink 6.4s linear infinite}
.shadow{animation:sh 3.2s ease-in-out infinite}
@keyframes breathe{0%,100%{transform:scale(1,1)}50%{transform:scale(1.012,1.028)}}
@keyframes sway{0%,100%{transform:rotate(-1.4deg)}50%{transform:rotate(1.4deg)}}
@keyframes sh{0%,100%{transform:scaleX(1)}50%{transform:scaleX(.96)}}
""",
    "wave": """
.pose{animation:rock 1.1s ease-in-out infinite}
.body{animation:hop 1.1s ease-in-out infinite}
.blink{animation:blink 4.4s linear infinite}
.hi{position:absolute;left:34px;top:62px;font:800 26px/1 var(--display);color:var(--cta);animation:hi 2.2s ease-in-out infinite;transform-origin:50% 100%}
@keyframes rock{0%,100%{transform:rotate(-3.5deg)}50%{transform:rotate(3.5deg)}}
@keyframes hop{0%,40%,100%{transform:translateY(0)}20%{transform:translateY(-8px)}}
@keyframes hi{0%,100%{transform:scale(.9) rotate(-8deg);opacity:0}15%,70%{transform:scale(1) rotate(-8deg);opacity:1}}
""",
    "cheer": """
.body{animation:jump .9s cubic-bezier(.3,0,.4,1) infinite}
.pose{animation:wig .45s ease-in-out infinite alternate}
.blink{animation:blink 3.6s linear infinite}
.shadow{animation:shj .9s cubic-bezier(.3,0,.4,1) infinite}
@keyframes jump{0%,100%{transform:translateY(0) scale(1.07,.93)}14%{transform:translateY(0) scale(.97,1.04)}50%{transform:translateY(-46px) scale(1,1)}86%{transform:translateY(0) scale(1,1)}}
@keyframes wig{from{transform:rotate(-2.5deg)}to{transform:rotate(2.5deg)}}
@keyframes shj{0%,14%,86%,100%{transform:scaleX(1);opacity:1}50%{transform:scaleX(.68);opacity:.45}}
.conf{position:absolute;top:-20px;width:9px;height:14px;border-radius:3px;animation:fall 1.8s linear infinite}
@keyframes fall{0%{transform:translateY(0) rotate(0)}100%{transform:translateY(500px) rotate(560deg)}}
""",
    "think": """
.pose{animation:ponder 4s ease-in-out infinite}
.body{animation:breathe 4s ease-in-out infinite}
.blink{animation:blink 4s linear infinite}
@keyframes ponder{0%,100%{transform:rotate(-2deg)}50%{transform:rotate(2.5deg)}}
@keyframes breathe{0%,100%{transform:scale(1,1)}50%{transform:scale(1.01,1.02)}}
.bubble{position:absolute;right:26px;top:44px;width:62px;height:48px;border-radius:24px;background:#fff;border:2.5px solid var(--ink);display:flex;align-items:center;justify-content:center;gap:5px;animation:pop 4s ease-in-out infinite;transform-origin:10% 100%}
.bubble i{display:block;width:8px;height:8px;border-radius:50%;background:var(--ink);animation:dot 1.2s ease-in-out infinite}
.bubble i:nth-child(2){animation-delay:.15s}.bubble i:nth-child(3){animation-delay:.3s}
.tb1,.tb2{position:absolute;border-radius:50%;background:#fff;border:2.5px solid var(--ink)}
.tb1{right:92px;top:100px;width:14px;height:14px}.tb2{right:104px;top:118px;width:9px;height:9px}
@keyframes pop{0%,100%{transform:scale(1)}50%{transform:scale(1.05)}}
@keyframes dot{0%,100%{transform:translateY(0);opacity:.35}40%{transform:translateY(-4px);opacity:1}}
""",
    "love": """
.body{animation:beat 1.4s ease-in-out infinite}
.pose{animation:sway 2.8s ease-in-out infinite}
.blink{animation:blink 4.2s linear infinite}
@keyframes beat{0%,40%,100%{transform:scale(1)}12%{transform:scale(1.045,1.035)}24%{transform:scale(.99)}32%{transform:scale(1.03)}}
@keyframes sway{0%,100%{transform:rotate(-1.6deg)}50%{transform:rotate(1.6deg)}}
.heart{position:absolute;opacity:0;animation:rise 2.8s ease-out infinite}
@keyframes rise{0%{transform:translateY(30px) scale(.4);opacity:0}20%{opacity:1}100%{transform:translateY(-90px) scale(1.1);opacity:0}}
""",
    "snap": """
.body{animation:snap 2.4s cubic-bezier(.3,0,.3,1) infinite}
.blink{animation:blink 4.8s linear infinite}
.flash{position:absolute;width:130px;height:130px;margin:-65px 0 0 -65px;border-radius:50%;background:radial-gradient(circle,#fff 0%,rgba(255,255,255,.85) 30%,rgba(255,255,255,0) 70%);opacity:0;animation:flash 2.4s ease-out infinite}
.spark{position:absolute;color:#FFC53D;font:800 20px/1 sans-serif;opacity:0;animation:tw 2.4s ease-out infinite}
@keyframes snap{0%,30%,100%{transform:scale(1) rotate(0)}38%{transform:scale(.97,1.03) rotate(-1.5deg)}46%{transform:scale(1.03,.97) rotate(1deg)}56%{transform:scale(1) rotate(0)}}
@keyframes flash{0%,40%{opacity:0;transform:scale(.4)}44%{opacity:1;transform:scale(1)}70%,100%{opacity:0;transform:scale(1.5)}}
@keyframes tw{0%,50%{opacity:0;transform:scale(.3) rotate(0)}62%{opacity:1;transform:scale(1.1) rotate(30deg)}90%,100%{opacity:0;transform:scale(.6) rotate(60deg)}}
""",
    "trophy": """
.body{animation:hop 1.6s cubic-bezier(.3,0,.4,1) infinite}
.pose{animation:proud 3.2s ease-in-out infinite}
.blink{animation:blink 4.8s linear infinite}
.spark{position:absolute;color:#FFC53D;font:800 18px/1 sans-serif;animation:tw 1.6s ease-in-out infinite}
.shadow{animation:shj 1.6s cubic-bezier(.3,0,.4,1) infinite}
@keyframes hop{0%,55%,100%{transform:translateY(0) scale(1,1)}10%{transform:translateY(0) scale(1.05,.95)}30%{transform:translateY(-22px) scale(.98,1.02)}50%{transform:translateY(0) scale(1.02,.98)}}
@keyframes proud{0%,100%{transform:rotate(-1.5deg)}50%{transform:rotate(1.5deg)}}
@keyframes tw{0%,100%{opacity:.2;transform:scale(.6)}50%{opacity:1;transform:scale(1.15) rotate(20deg)}}
@keyframes shj{0%,55%,100%{transform:scaleX(1)}30%{transform:scaleX(.8)}}
""",
    "sleep": """
.body{animation:breathe 4.4s ease-in-out infinite}
.pose{transform:rotate(-3deg)}
.z{position:absolute;font:800 22px/1 var(--display);color:#8B7CF6;opacity:0;animation:zz 4.4s ease-out infinite}
@keyframes breathe{0%,100%{transform:scale(1,1) translateY(0)}45%{transform:scale(1.02,1.04) translateY(-2px)}}
@keyframes zz{0%{transform:translate(0,20px) scale(.5);opacity:0}20%{opacity:1}100%{transform:translate(34px,-70px) scale(1.15);opacity:0}}
""",
}


def _common(t: Theme) -> str:
    return f"""
:root{{--ink:{t.ink};--cta:{t.cta};--display:{t.display_css}}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:{t.body_css};color:{t.ink};background:{t.bg}}}
.card{{width:{W}px;height:{H}px;position:relative;overflow:hidden;background:radial-gradient(120% 80% at 50% 34%,{t.glow} 0%,{t.bg} 62%)}}
.stage{{position:absolute;left:{(W - STAGE) // 2}px;top:58px;width:{STAGE}px;height:{STAGE}px}}
.body,.pose{{position:absolute;inset:0;transform-origin:50% 96%}}
.pose img,.pose svg{{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:block}}
.shadow{{position:absolute;left:50%;top:{58 + STAGE - 14}px;width:150px;height:16px;margin-left:-75px;border-radius:50%;background:rgba(0,0,0,.1)}}
.tag{{position:absolute;left:20px;top:18px;padding:5px 10px;border-radius:999px;background:{t.selected};color:{t.accent_text};font:700 11px/1 {t.body_css};letter-spacing:.4px;text-transform:uppercase}}
.label{{position:absolute;left:20px;right:20px;bottom:18px}}
.label h3{{margin:0;font:800 19px/1.15 {t.display_css};letter-spacing:-.3px}}
.label p{{margin:4px 0 0;font:600 12.5px/1.35 {t.body_css};color:{t.muted}}}
.blink{{opacity:0}}
@keyframes blink{{0%,90%,93.5%,100%{{opacity:0}}91%,92.5%{{opacity:1}}}}
@keyframes dblink{{0%,84%,86%,89%,91%,100%{{opacity:0}}84.6%,85.4%,89.6%,90.4%{{opacity:1}}}}
@media (prefers-reduced-motion: reduce){{*{{animation:none!important}}}}
"""


def _fx(t: Theme, state: str) -> str:
    if state == "wave":
        return '<div class="hi">Hi!</div>'
    if state == "cheer":
        cols = [t.cta] + t.series[1:4] + ["#FF7EB6"]
        return "".join(f'<i class="conf" style="left:{14 + i * 28}px;background:{cols[i % len(cols)]};'
                       f'animation-delay:-{(i * 0.37) % 1.8:.2f}s;animation-duration:{1.6 + (i % 4) * 0.25:.2f}s"></i>' for i in range(12))
    if state == "think":
        return '<div class="tb2"></div><div class="tb1"></div><div class="bubble"><i></i><i></i><i></i></div>'
    if state == "love":
        h = ('<svg class="heart" style="left:{l}px;top:{t}px;animation-delay:{d}s" width="{s}" height="{s}" viewBox="0 0 24 22">'
             '<path d="M12 21s-9-5.6-9-12.2A5 5 0 0 1 12 5a5 5 0 0 1 9 3.8C21 15.4 12 21 12 21z" fill="#FF6B8B" stroke="' + t.ink + '" stroke-width="1.6"/></svg>')
        return "".join(h.format(l=l, t=tp, d=d, s=s) for l, tp, d, s in [(60, 150, 0, 22), (282, 130, .9, 18), (250, 200, 1.8, 26), (40, 230, 2.3, 16)])
    if state == "snap":
        sp = "".join(f'<span class="spark" style="left:{l}px;top:{tp}px;animation-delay:{d}s">✦</span>' for l, tp, d in [(270, 250, 0), (300, 216, .12), (232, 290, .22)])
        return '<div class="flash" style="left:116px;top:170px"></div>' + sp
    if state == "trophy":
        return "".join(f'<span class="spark" style="left:{l}px;top:{tp}px;animation-delay:{d}s">✦</span>' for l, tp, d in [(300, 60, 0), (250, 44, .5), (318, 128, 1.0)])
    if state == "sleep":
        return "".join(f'<span class="z" style="left:{l}px;top:{tp}px;font-size:{s}px;animation-delay:{d}s">z</span>'
                       for l, tp, d, s in [(236, 96, 0, 18), (236, 96, 1.47, 24), (236, 96, 2.93, 30)])
    return ""


def board(ctx: Ctx, state: str) -> str:
    t = ctx.theme
    tag, used, note = STATES[state]
    pose = ctx.mascot.get(state) or ctx.mascot.get("idle")
    blink = ctx.blink.get(state) if state in ctx.mascot else ctx.blink.get("idle")
    if pose:
        layers = f'<img src="{pose}" alt="">'
        if blink:
            closed = ' style="opacity:1;animation:none"' if state == "sleep" else ""
            layers += f'<img class="blink" src="{blink}" alt=""{closed}>'
    else:
        layers = mascot_svg(t, STAGE, "none")
    data_props = json.dumps({"$preview": {"width": W, "height": H}})
    name = t.mascot_name or t.display_name
    return (f"<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<title>{name} · {tag}</title>\n"
            f"<script src=\"./support.js\"></script>\n</head>\n<body>\n<x-dc>\n<helmet>\n{t.fonts_link()}\n"
            f"<style>{_common(t)}{MOTION[state]}</style>\n</helmet>\n"
            f'<div class="card" data-state="{state}"><div class="tag">{tag}</div><div class="shadow"></div>'
            f'<div class="stage"><div class="body"><div class="pose">{layers}</div></div></div>{_fx(t, state)}'
            f'<div class="label"><h3>{used}</h3><p>{note}</p></div></div>\n</x-dc>\n'
            f"<script type=\"text/x-dc\" data-dc-script data-props='{data_props}'>\nclass Component extends DCLogic {{\n"
            f"renderVals() {{ return {{}}; }}\n}}\n</script>\n</body>\n</html>\n")


def file_name(index: int, state: str) -> str:
    return f"M{index:02d}-{state.capitalize()}.dc.html"
