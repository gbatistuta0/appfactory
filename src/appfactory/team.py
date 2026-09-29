"""team_brief — render the team process docs for one app from its spec.

templates/team/  → docs/TEAM.md, docs/team/{ios,backend,store}.md
templates/docs/  → docs/onboarding-plan.md (from design/screens.json), store/aso-research.md,
                   docs/CHECKLIST.md

The team way of working: a lead + three role sessions, coordination via SendMessage
to the lead, only the lead talks to the founder, postponed work in GitHub Issues, gh as the configured GitHub account
per command, no Chrome automation, no secrets, green tests, commit own paths, only the lead pushes.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

from . import issues, spec as spec_mod
from .app import strip_blocks as app_mod_strip
from .design import pricing, screens as screens_mod

PKG_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_ROOT = PKG_ROOT / "templates" if (PKG_ROOT / "templates").is_dir() else Path(__file__).resolve().parent / "templates"
TEAM_DIR = TEMPLATES_ROOT / "team"
DOCS_DIR = TEMPLATES_ROOT / "docs"

OUTPUTS = {
    TEAM_DIR / "TEAM.md": "docs/TEAM.md",
    TEAM_DIR / "ios.md": "docs/team/ios.md",
    TEAM_DIR / "backend.md": "docs/team/backend.md",
    TEAM_DIR / "store.md": "docs/team/store.md",
    DOCS_DIR / "onboarding-plan.md": "docs/onboarding-plan.md",
    DOCS_DIR / "aso-research.md": "store/aso-research.md",
    DOCS_DIR / "CHECKLIST.md": "docs/CHECKLIST.md",
}
_VAR = re.compile(r"\{\{(\w+)\}\}")

ANALYTICS = [
    ("onboarding_start", "—", "first onboarding screen shown"),
    ("onboarding_step_view", "step, kind", "every onboarding screen"),
    ("onboarding_answer", "step, question, value", "every answer (attribution included)"),
    ("onboarding_skip", "step", "optional screen skipped (permission, account)"),
    ("onboarding_complete", "—", "plan ready reached"),
    ("paywall_view", "variant (hard/offer), from (placement)", "any paywall shown"),
    ("paywall_plan_select", "plan", "plan tile tapped"),
    ("paywall_dismiss", "variant", "paywall closed (drives the offer)"),
    ("purchase_start / purchase_success / purchase_fail / purchase_cancel", "product, plan, variant", "purchase flow"),
    ("trial_start", "product", "intro offer started"),
]


def render_text(text: str, values: dict[str, str]) -> str:
    missing = sorted({m for m in _VAR.findall(text) if m not in values})
    if missing:
        raise KeyError(f"template variables without a value: {missing}")
    return _VAR.sub(lambda m: values[m.group(1)], text)


def option_flags(spec: dict[str, Any]) -> dict[str, bool]:
    """Flags for the `<!-- @if flag -->` blocks in the team docs: the run options (see app.feature_flags)."""
    from . import app as app_mod, config as cfg
    flags = app_mod.feature_flags(spec)
    flags["github_issues"] = spec_mod.option(spec, "github_issues") and cfg.first_disabled(("github",)) is None
    return flags


def _cell(s: Any) -> str:
    return str(s or "—").replace("|", "\\|").replace("\n", " ")


def _content(s: dict[str, Any]) -> str:
    bits = [s.get("title", "")]
    if s.get("subtitle"):
        bits.append(f"— {s['subtitle']}")
    return " ".join(bits)


def _input(s: dict[str, Any]) -> str:
    if s.get("kind") == "question":
        opts = " / ".join(o.get("label", "") for o in s.get("options", []))
        return f"{'multi' if s.get('select') == 'multi' else 'single'}: {opts}"
    if s.get("kind") == "picker":
        pk = s.get("picker") or {}
        extra = " + kg/lb toggle" if screens_mod.is_weight_picker(pk) else ""
        return f"{pk.get('type')} picker{extra}"
    if s.get("kind") == "preferences":
        return " / ".join(t.get("title", "") for t in s.get("toggles", []))
    if s.get("kind") in ("paywall", "offer"):
        return "purchase"
    return "—"


def plan_tables(doc: dict[str, Any], prefix: str) -> dict[str, str]:
    onb = doc.get("onboarding", [])
    rows = [f"| {i} | {_cell(s['id'])} | {_cell(s.get('kind'))} | {_cell(_content(s))} | {_cell(_input(s))} | {_cell(s.get('motion'))} |"
            for i, s in enumerate(onb, 1)]
    main = [f"| A{i:02d} | {_cell(s['id'])} | {_cell(s.get('kind'))} | {_cell(_content(s))} | {_cell(s.get('motion'))} |"
            for i, s in enumerate(doc.get("main", []), 1)]
    data = [f"| {_cell(s['id'])} | {_cell(_input(s))} | {_cell(s['data'])} |" for s in onb if s.get("data")]
    events = [f"| `{prefix}{e}` | {p} | {w} |" if " / " not in e else
              f"| {' / '.join(f'`{prefix}{x}`' for x in e.split(' / '))} | {p} | {w} |" for e, p, w in ANALYTICS]
    return {"screen_table": "\n".join(rows), "main_table": "\n".join(main),
            "data_table": "\n".join(data) or "| — | — | — |", "analytics_table": "\n".join(events)}


def values(spec: dict[str, Any], doc: dict[str, Any], sessions: dict[str, str] | None = None,
           repo: str | None = None) -> dict[str, str]:
    slug = spec_mod.slug(spec["name"])
    sess = {"lead": "lead", "ios": f"{slug}-ios", "backend": f"{slug}-backend", "store": f"{slug}-store"}
    sess.update(sessions or {})
    design = spec.get("design") or {}
    mascot = design.get("mascot") or {}
    tokens = {**spec_mod.DEFAULTS["design"]["tokens"], **(design.get("tokens") or {})}
    fonts = {**spec_mod.DEFAULTS["design"]["fonts"], **(design.get("fonts") or {})}
    prods = []
    for offering in ("default", "offer"):
        for p in pricing.plans(spec, offering):
            prods.append(f"| `{p['id']}` | {p['name']} | {p['price']} | {p['trial'] or 'no trial'} | {offering} | level {p['level']} |")
    usage = spec.get("usage") or {}
    caps = ", ".join(f"{k} {v}/day" for k, v in (usage.get("daily_caps") or {}).items())
    ai = spec.get("ai") or {}
    anchor = spec.get("offer_anchor") or {}
    mascot_line = (f"Mascot: {mascot.get('name')}, a {mascot.get('species', 'character')} "
                   f"(states: {', '.join(mascot.get('states') or spec_mod.MASCOT_STATES)})." if mascot.get("name")
                   else "No mascot configured (spec design.mascot is empty).")
    return {
        "app": spec["name"], "display_name": spec.get("display_name") or spec["name"], "bundle_id": spec["bundle_id"],
        "slug": slug, "repo": repo or f"{issues.repo_owner() or '<owner>'}/{slug}", "date": datetime.date.today().isoformat(),
        "lead_session": sess["lead"], "ios_session": sess["ios"], "backend_session": sess["backend"],
        "store_session": sess["store"], "mascot_line": mascot_line,
        "mascot_states": ", ".join(mascot.get("states") or spec_mod.MASCOT_STATES),
        "tokens_table": "\n".join(f"| {k.replace('_', ' ')} | `{v}` |" for k, v in tokens.items() if isinstance(v, str)),
        "display_font": fonts.get("display", ""), "body_font": fonts.get("body", ""),
        "ai_model": ai.get("model", ""), "ai_fallback": ai.get("fallback_model", ""),
        "app_locales": ", ".join(spec["locales"]["app"]), "store_locales": ", ".join(spec["locales"]["store"]),
        "event_prefix": spec.get("analytics", {}).get("event_prefix") or f"{slug}_",
        "products_table": "| Product id | Plan | USD | Intro | Offering | Level |\n|---|---|---|---|---|---|\n" + "\n".join(prods),
        "placements": ", ".join(f"`{p}`" for p in spec.get("placements", [])),
        "offer_placements": ", ".join(f"`{p}`" for p in spec.get("offer_placements", [])),
        "usage": (f"{usage.get('free_lifetime_scans', 0)} lifetime free AI result(s); subscribers {caps or 'uncapped'}; "
                  f"entitlement grace {usage.get('entitlement_grace_hours', 0)} h"),
        "offer_anchor": f"less than one {anchor.get('item', '?')} a month (`{anchor.get('label_key', '')}`)",
        "onboarding_screens": str(len(doc.get("onboarding", [])) or design.get("onboarding_screens", 26)),
        "consent": "yes" if (spec.get("consent") or {}).get("health") else "no",
        **plan_tables(doc, spec.get("analytics", {}).get("event_prefix") or f"{slug}_"),
    }


def brief(app_dir: str | Path, sessions: dict[str, str] | None = None, repo: str | None = None,
          overwrite: bool = False) -> dict[str, Any]:
    """Render TEAM.md, the role briefs, onboarding-plan.md, aso-research.md and CHECKLIST.md."""
    app = Path(app_dir).expanduser()
    if not spec_mod.path(app).exists():
        return {"ok": False, "error": f"{spec_mod.SPEC_FILE} missing"}
    spec = spec_mod.load(app)
    doc = screens_mod.load(app) if screens_mod.path(app).exists() else screens_mod.skeleton(spec)
    vals = values(spec, doc, sessions, repo)
    flags = option_flags(spec)
    written, kept = [], []
    for src, rel in OUTPUTS.items():
        dst = app / rel
        if dst.exists() and not overwrite:
            kept.append(rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = app_mod_strip(src.read_text(encoding="utf-8"), flags)
        dst.write_text(render_text(text, vals), encoding="utf-8")
        written.append(rel)
    return {"ok": True, "written": written, "kept": kept,
            "sessions": {k: vals[f"{k}_session"] for k in ("lead", "ios", "backend", "store")},
            "screens_source": "design/screens.json" if screens_mod.path(app).exists() else "skeleton (no design/screens.json yet)"}
