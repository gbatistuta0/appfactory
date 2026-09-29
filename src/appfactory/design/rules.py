"""Structural design rules every app respects, whatever its brief-driven look.

These are platform and quality constraints, not a style: the brief decides palette, type, layout and
illustration; these decide what must hold regardless. Machine-checkable parts (WCAG AA contrast of the
brief palette, no emoji in authored boards) are enforced by the gates; the rest is confirmed in the
fidelity review (`platform_rules_ok`) and the screenshots review (`store_rules_ok`).
"""

from __future__ import annotations

import re
from typing import Any

APP_RULES = [
    "Native iOS 26: boards depict the SYSTEM Liquid Glass chrome — the TabView tab bar, NavigationStack "
    "navigation bars/toolbars (large title, system back button, glass toolbar buttons), system sheets and "
    "glass controls. The brief styles the content, never replaces the system chrome (no custom-drawn tab "
    "bars, top bars or fake glass).",
    "iOS 26 sheets get an opaque background — Liquid Glass lets the content behind ghost through.",
    "System tab bar; the main action is the search-role tab. Its brand color needs an original-rendering "
    "image (a template image is tinted away); the bar minimizes on scroll.",
    "SF Symbols, never emoji, in the UI (emoji drew as empty boxes).",
    "Compact layouts that fit iPhone SE; pinned bottom buttons sit 16 pt above the bottom edge.",
    "Text colors meet WCAG AA against their background (4.5:1 body text, 3:1 large/bold text and CTA labels).",
    "Paywall buttons are sized per language (the longest localization must fit without truncation).",
    "Rating prompts only at success moments, never in onboarding; no notification prompt in onboarding.",
]

STORE_RULES = [
    "Every language renders the approved Claude Design store boards themselves — only the words and the "
    "captures change.",
    "Real captures inside the frames; Home Screen widgets are real widget captures.",
    "Watch faces show 9:41.",
    "The mascot and directional layouts are mirrored for RTL languages (ar, he).",
    "A safe zone keeps captions, badges and overlays off the app's buttons and key UI.",
]

# Pictographic emoji + dingbats + regional indicators (flags); arrows/★ are covered by other rules.
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")


def has_emoji(text: str) -> bool:
    return bool(_EMOJI.search(text or ""))


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# (foreground token, background token or literal, minimum ratio)
AA_PAIRS = [("ink", "background", 4.5), ("muted", "background", 4.5), ("accent_text", "background", 4.5),
            ("#FFFFFF", "cta", 3.0)]


def contrast_problems(tokens: dict[str, Any]) -> list[str]:
    errs = []
    for fg, bg, need in AA_PAIRS:
        f = fg if fg.startswith("#") else tokens.get(fg)
        b = bg if bg.startswith("#") else tokens.get(bg)
        if not f or not b:
            continue
        try:
            ratio = contrast(str(f), str(b))
        except ValueError:
            continue
        if ratio < need:
            errs.append(f"{fg} on {bg} contrast {ratio:.2f}:1 < {need}:1 (WCAG AA)")
    return errs
