"""pipeline_* — the app production pipeline: manifest + stage gates.

The MCP enforces the stage order (it is not left to Claude's memory). ASO is a mandatory
stage; metadata/deliver do not run until ASO is complete (hard gate).
Manifest: <app_dir>/.appfactory/state.json
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from . import aso

STAGES = [
    "scaffold", "repo", "design_research", "design", "features", "backend", "ai_proxy",
    "icon", "asc_app", "iap",
    # --- once the app is fully built (LAST) ---
    "localize", "analytics", "aso", "metadata", "screenshots", "app_preview", "deliver",
    "custom_product_pages", "testflight",
    # --- submission prep (after TestFlight, before the human submission) ---
    "submission_prep",
]

STAGE_INSTRUCTIONS = {
    "scaffold": "Build app.spec.json (spec.build: monetization subscription by default, 6 app locales, 8 store locales, 8 placements, prices/intro offers/grace period, caps, AI (ai.enabled: false for a non-AI app) + models, design tokens, mascot) → app_scaffold(name, bundle_id, spec=…) → storekit_parity must be clean. The scaffold strips the credit economy in subscription mode, the HealthKit module unless spec.health.enabled, and renders the backend mode (backend_render). After any spec edit run app_sync_spec. Skeleton: system TabView (Create as the search-role tab) + Settings (subscription/restore/manage/privacy/terms/support/version). Native iOS 26: built with the iOS 26 SDK (Xcode 26+), deployment target 17.5, iOS 26 APIs behind #available.",
    "repo": "github_create_repo (PRIVATE, under the configured GitHub account) + push. Postponed work → github_issues_bootstrap once, then github_issue_create (labels ios/backend/store/lead/founder + next/later). Push after every stage.",
    "design_research": "Research before any board: design_research_collect(app_dir, terms=<category keywords>, countries=[us, gb, de, jp, br]) downloads the category leaders' (search + top-grossing/top-free charts) App Store screenshots + icons to design/research/apps/. Read every image and analyze: visual look, palette, type, components, density, illustration, onboarding + paywall patterns, and the screenshot storytelling (frame-1 hook, caption style/length, device framing vs full-bleed, backgrounds, feature sequencing, badges within Apple's rules) \u2014 what the leaders share vs how they differ. Write design/research/brief.md + brief.json (design_research_brief_template): a blended, differentiated direction for THIS app's purpose; every section cites the reference ids it borrows from and says what it does differently; screenshots section cites \u22654 competitor screenshot sets. Never copy a competitor's brand, assets or trade dress (no_copy: true). Palette/type must not equal the template defaults or another factory app. Gate: \u22656 references on disk + valid brief.",
    "design": "If the design service (claude-design MCP) is enabled, Claude Design is the design tool; otherwise author the boards locally (HTML in design/project/, or provided assets) and skip the upload/open_url steps. design/research/brief.json is the only source of the look (no Stitch, no image generators, no fixed template look). Spec design.tokens/fonts = the brief's palette/typography. design_screens_skeleton(write=True) \u2192 onboarding follows the brief's flow \u2192 adapt EVERY screen individually (no dark patterns: no fake stats/reviews, no rating prompt inside onboarding, no notification prompt; kg/lb on every weight picker; hard paywall + offer) \u2192 design_generate \u2192 design/scaffold/ holds STRUCTURE ONLY. AUTHOR every board listed in upload_plan.authored in Claude Design from the brief (get_claude_design_prompt, read_design_skill('hifi-design')), keeping the scaffold's structure, real copy and prices; sync each authored file to design/project/ \u2192 upload the rest (upload_plan calls) \u2192 design_record_upload(project_id, open_url) \u2192 founder review via open_url. Mascot (spec.design.mascot): approved pose PNGs \u2192 mascot_blink \u2192 mascot_assets \u2192 MascotView(state:); never rig from a separate parts sheet. Boards depict the native iOS 26 Liquid Glass system chrome (TabView tab bar, navigation bars/toolbars, sheets, glass controls); the brief styles the content only. Translate to SwiftUI (DesignSystem tokens, Motion keyframes; system chrome, never custom tab/top bars) and write .appfactory/verify/design_review.json {fidelity_ok:true} after comparing every screen with its Claude Design board. Gate: research + brief valid, screens/tokens derived from the brief, every authored board differs from its scaffold, upload recorded after the current brief and unchanged, fidelity.",
    "features": "Replace the placeholder onboarding questions (≥5 questions, spec screen count, nothing preselected), fill _shared/analysis.ts (prompt + strict JSON schema) and the result screen, the paywall benefits and personalization. Keep the error routing (402 paywall / 429 cap / 403 consent / 503 retry, never a paywall). App Store rating requests are MANDATORY at success moments and FORBIDDEN in onboarding (App Review rejects an onboarding rating step): keep RatingPolicy (spec.rating: N successes on M days, milestones, ≥60-day gap, ≤3 a year, never after a failure) and wire RatingPolicy.shared.request(…) to the app's real success moment + .ratingRequest($trigger) on a view that stays on screen (the features gate fails otherwise). Native iOS 26 chrome: system TabView (Tab API, main action as the search-role tab, minimizes on scroll), NavigationStack .navigationTitle/.toolbar (system back button), system sheets with presentationDetents + opaque surface, .glass/.glassProminent for floating controls behind #available(iOS 26, *) — no custom tab/top bars (the features gate fails on them and on a pre-iOS 26 build SDK). Unit + UI tests green (build_test), then .appfactory/verify/features.json {\"build_ok\": true, \"test_ok\": true, \"sdk\": \"iphonesimulator26.x\"}. End-to-end: open the Maestro Viewer (maestro MCP open_maestro_viewer, http://localhost:7777) so the founder can watch, drive the installed app on the simulator with inspect_screen/run, save every passing flow as YAML in .maestro/flows/ (the template ships the launch → onboarding → paywall smoke flow; never tap a paid/purchase button), then maestro_test(app_dir, tags=\"smoke\") must be green (runs through tools/maestro-live, which opens the Viewer for the run; never plain `maestro test` on the Mac; writes .appfactory/verify/maestro.json; the features gate and testflight_ship require it).",
    "backend": "backend_render → supabase_create_project (AppFactory org) → firebase_setup (Firebase is bundled, but only production App Store builds send: AnalyticsGate). Anonymous auth + Sign in with Apple linking. deno task test green.",
    "ai_proxy": "Backend deploy (APPROVAL: live write): legal_render → legal_check → backend_deploy(dry_run=True) → founder approves → backend_deploy → legal_verify. Eval: backend/eval with --dry-run then (APPROVAL: spend) a capped run → pricing_unit_economics writes the measured cost per call into store/pricing.md. Write .appfactory/verify/ai_proxy.json.",
    "icon": "App icon from Claude Design when the design service is enabled (otherwise author the board locally or provide a 1024\u00d71024 icon.png and skip the upload): author B01-AppIcon.dc.html from the brief's palette + illustration direction (the scaffold only fixes the 1024\u00d71024 slot; founder approves via open_url) \u2192 render_preview \u2192 design_export_png(serve_url, <app>/design/icon.png, 1024, 1024) \u2192 design_generate (copies it into the project) \u2192 upload + design_record_upload \u2192 icon_install. No competitor icon elements. icon_generate (fal) is opt-in reference drafting only and never installs. Gate: verify/icon.json source=claude_design + appiconset holds that master + icon.png uploaded.",
    "asc_app": "Phase 0 (founder awake): asc_create_bundle_id(app_dir=…) → store_setup target=capabilities (plan → check → APPROVAL → apply; BEFORE any key/profile/signing step) → asc_create_app. Write verify/asc_app.json.",
    "iap": "metadata_render_listing → fill the IAP copy → store_setup plan + check (asc, then rc) → APPROVAL with the full diff → apply (out-of-band `appfactory approve <id>`, then re-call with approval_id): subscription group, yearly+weekly with a 3-day free intro per territory, trial-less yearly.offer, EUR/BRL/TRY overrides, prices in EVERY territory incl. the unsold spec.store.excluded_territories (CHN: else MISSING_PRICING_DATA at submission), Billing Grace Period, server notifications URL, app availability (v2, excluded territories off), categories (spec.store), content rights, FREE price schedule, brand copyright, review contact + demoAccountRequired false + notes from store/review-notes.md → RevenueCat (paste rc_apple_notification_url; the one MANUAL line), RC project/app/products/entitlement premium/offerings default+offer/targeting rule with all placements. Execute any returned mcp_plan with the RevenueCat MCP. No subscription may stay in MISSING_METADATA.",
    "localize": "(APP DONE) Scripts/sync_strings.py, then localize_apply for spec.locales.app only (en, es, pt-BR, de, fr, tr) until LocalizationCompletenessTests and LocalizationUITests pass, and LayoutAuditUITests with TEST_RUNNER_AUDIT_LANGS=all is clean on the SE and the Pro Max (truncation by OCR, English leftovers, missing glyphs, overflow). Numbers in the user's digits (Units.plainNumber: Arabic-Indic in ar), dates/ages Gregorian (BirthYears), a system font for scripts the brand fonts lack, RTL checked in ar/he. Legal sources store/privacy/*.md in every app language.",
    "analytics": "(END OF DEVELOPMENT) Full instrumentation: every screen calls Tracker.screen(<name>) (screen_enter with prev_screen + dwell), every funnel event from the fixed Tracker.Event catalog, app events only with the spec prefix. AnalyticsGate stays production-only. Build + tests green, then .appfactory/verify/analytics.json {\"per_screen\": true, \"build_ok\": true}.",
    "aso": "aso_run → ASO research (store/aso-research.md method: competitors per storefront, localized titles/prices, autocomplete a–z, popularity proxy, niche score) → fill the metadata for the 8 store locales → metadata_listing_check → aso_complete.",
    "metadata": "metadata_export → fastlane/metadata (does not run until ASO is complete).",
    "screenshots": "REQUIRED. The layout comes from the brief's screenshot concept, authored in Claude Design (if the design service is disabled: author the boards locally and skip the upload steps). If the research is older than 45 days, re-run design_research_collect and re-study the competitors' current screenshot sets; update the brief's screenshots section (analysis + concept + boards, \u22654 cited sets). Write the app-specific ASO captions (marketing/screenshots/copy/<locale>.json, one entry per concept board) \u2192 capture en-US raw per concept board (screenshot_capture name=<NN_shot> from store_layout.json shots) \u2192 design_generate \u2192 AUTHOR the ST boards in Claude Design from the concept with the real captions/captures inside the frames \u2192 sync, upload, design_record_upload \u2192 screenshot_build_all (applies store_layout.json, captures the concept's shots for every store locale, brands, syncs). Then verify/screenshots_review.json {fonts_modern, colors_match_app, matches_claude_design: true}. No manual capture. Captures run under the store status bar (9:41 on a fixed date, full bars, NOT charging: App Review flagged the bolt) with AppleLanguages + AppleLocale; widgets/SpringBoard/Watch need Scripts/sim_store_prep.sh (system language + region, reboot, clean install) first. build.mjs uses per-script fonts, RTL and CJK/Thai line breaks; FIT warnings mean a caption to shorten. Review every slide by eye: real app, real numbers, no English leftovers, no truncation.",
    "app_preview": (
        "App Preview, authored by Claude from REAL app footage (the Remotion template is gone). "
        "preview_brief → marketing/preview/BRIEF.md (HyperFrames, destination app-store-preview) → per source locale: "
        "Scripts/sim_store_prep.sh (language, region, 9:41 status bar, clean install) + `xcrun simctl io <udid> "
        "recordVideo` of the seeded app (DEBUG launch flags, no AI spend) into marketing/preview/recordings/<locale>/ → "
        "author the composition with the `hyperframes` skill (animated phone frame, kinetic captions in a top band, "
        "punch-ins, crossfades; deterministic: no Math.random/timers; Apple's real-footage rule beats any flourish; "
        "no hands/devices/prices) → render 886x1920, <=30 fps, H.264, 15–30 s, stereo AAC music or silent into "
        "fastlane/app_previews/<locale>/ (one per spec.preview locale; spec.preview.shared documents reuse, e.g. "
        "en-GB→en-US) → SELF-REVIEW: preview_review_sheets (contact 2 fps 6x5, phone 1 fps 360 px 5x3, 12-frame "
        "strip at the fastest cut), open them, preview_review_log scores 1–10 (hook in the first 2 s, readability "
        "at 360 px, motion, variety every 2–4 s, brand, music sync) + the 3 worst problems with timestamps; fix, "
        "re-render, repeat until all 8+ on the final file → preview_check clean → founder's go → "
        "preview_upload(dry_run=False) + `appfactory approve <id>` → .appfactory/verify/app_preview.json {\"uploaded\": true}."
    ),
    "deliver": "deliver_metadata + deliver_screenshots (asc CLI, MD5-incremental, no fastlane retry duplicates) → deliver_screenshots_audit must be clean (per locale and display type: exact files, order, COMPLETE, MD5) → deliver_subscription_review_screenshots (store/review-screenshots/<product key>.png, real sandbox prices).",
    "custom_product_pages": (
        "Custom Product Pages — one per Search Ads THEME. cpp_build_all (app_id, app_apple_id, themes) → "
        "per theme: CPP create→version→localization + a theme-specific screenshot set. Themes come from the "
        "keyword/theme clusters in the ASO output. Write the returned deep-link URLs (the Ad Ops campaign→CPP "
        "mapping) to .appfactory/verify/custom_product_pages.json {pages:[{theme,id,url}], screenshots_uploaded:true}."
    ),
    "testflight": "maestro_test(app_dir, tags=\"smoke\") green on the current build (testflight_ship refuses otherwise) → testflight_ship (app_dir, project, scheme, bundle_id) → fully automatic: distribution cert + temporary keychain → archive → App Store profiles for the app AND every extension in project.yml (exact bundle-id match: ASC's filter is a substring match), created right before export (Xcode sweeps earlier ones) → manual-signing export (manageAppVersionAndBuildNumber false) → `asc builds upload`. Bump CURRENT_PROJECT_VERSION for every upload. App Store publishing only with the user's approval.",
    "submission_prep": "(post-TestFlight) store_setup check must show no CONFLICT/ERROR (availability, categories, content rights, price, copyright, review notes all synced) + subscription/group localizations complete + review screenshots uploaded (no MISSING_METADATA) + deliver_screenshots_audit clean + App Privacy: Apple has no API and Chrome automation is banned → put the answers from backend/PRIVACY.md (== Privacy/PrivacyInfo.xcprivacy) into NEEDS_HUMAN for the founder. SUBMISSION is human-only and in the ASC web UI: the version page → In-App Purchases and Subscriptions → select every subscription → Add for Review → Submit (a first subscription cannot be submitted through the API; asc_submit_for_review refuses). Write verify/submission_prep.json after confirmation.",
}


def manifest_path(app_dir: str | Path) -> Path:
    return Path(app_dir).expanduser() / ".appfactory" / "state.json"


def init(app_dir: str | Path, app: str, bundle_id: str) -> dict[str, Any]:
    p = manifest_path(app_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "app": app,
        "bundle_id": bundle_id,
        "dir": str(Path(app_dir).expanduser()),
        "created_at": time.time(),
        "stages": {s: "pending" for s in STAGES},
    }
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def load(app_dir: str | Path) -> dict[str, Any] | None:
    p = manifest_path(app_dir)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    stages = data.setdefault("stages", {})
    # apps whose design was done before design_research existed are not sent back to research
    if "design_research" not in stages and stages.get("design") == "done":
        stages["design_research"] = "done"
    return data


def _save(app_dir: str | Path, data: dict[str, Any]) -> None:
    manifest_path(app_dir).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def mark(app_dir: str | Path, stage: str, status: str = "done") -> dict[str, Any]:
    data = load(app_dir)
    if data is None:
        return {"ok": False, "error": "no manifest (run app_scaffold first)"}
    if stage not in STAGES:
        return {"ok": False, "error": f"unknown stage: {stage}"}
    if status == "done":
        from . import gates
        g = gates.validate_stage(app_dir, stage)
        if not g["ok"]:
            return {"ok": False, "stage": stage, "status": data["stages"].get(stage),
                    "gate_failure": g,
                    "error": f"'{stage}' gate failed — NOT marked done: {g['reason']}"}
    data["stages"][stage] = status
    _save(app_dir, data)
    return {"ok": True, "stage": stage, "status": status}


def status(app_dir: str | Path) -> dict[str, Any]:
    data = load(app_dir)
    if data is None:
        return {"ok": False, "error": "no manifest"}
    nxt = next((s for s in STAGES if data["stages"].get(s) != "done"), None)
    out = {"ok": True, "app": data["app"], "stages": data["stages"], "next": nxt}
    from . import gates
    na = {s: off for s in STAGES if (off := gates.stage_disabled_service(s))}
    from . import options as options_mod
    na.update({s: f"option:{o}" for s in STAGES if s not in na
               and (o := options_mod.stage_disabled_option(app_dir, s))})
    if na:
        out["n/a"] = na  # stage → disabled service (reported, skipped by its gate)
    return out


def next_step(app_dir: str | Path) -> dict[str, Any]:
    data = load(app_dir)
    if data is None:
        return {"ok": False, "error": "no manifest"}
    nxt = next((s for s in STAGES if data["stages"].get(s) != "done"), None)
    if nxt is None:
        return {"ok": True, "done": True, "message": "All stages done. Submission needs the founder's approval."}
    return {"ok": True, "next_stage": nxt, "status": data["stages"][nxt],
            "instruction": stage_instruction(app_dir, nxt)}


AI_OFF_INSTRUCTIONS = {
    "features": ("(spec.ai.enabled=false — non-AI app) Build the app's core feature on-device (no analyze call, "
                 "no _shared/analysis.ts to fill). Everything else in the features stage still applies: "
                 "onboarding questions (≥5, nothing preselected), paywall benefits, personalization, rating "
                 "requests at success moments (never in onboarding), native iOS 26 chrome, analytics coverage."),
    "ai_proxy": ("(spec.ai.enabled=false — AI n/a) Backend deploy WITHOUT the analyze function and without "
                 "FAL_KEY (APPROVAL: live write): legal_render → legal_check → backend_deploy(dry_run=True) → "
                 "founder approves → backend_deploy (usage-status, delete-account, legal, rc-webhook) → "
                 "legal_verify. No eval, no AI unit economics. The gate checks the deploy marker + legal pages."),
}


# Run options that reshape stage instructions: option → (stage, regex, replacement), applied while the
# option is off. tests/test_run_options_effects.py asserts each pattern still matches STAGE_INSTRUCTIONS.
OPTION_OFF_EDITS: dict[str, list[tuple[str, str, str]]] = {
    "github_issues": [("repo", r" Postponed work → github_issues_bootstrap once, then github_issue_create \([^)]*\)\.", "")],
    "e2e_smoke": [
        ("features", r" End-to-end: open the Maestro Viewer.*$",
         " End-to-end smoke tests are n/a (the user turned off the e2e_smoke run option): no .maestro workspace is required."),
        ("testflight", r'maestro_test\(app_dir, tags="smoke"\) green on the current build \(testflight_ship refuses otherwise\) → ', ""),
    ],
    "rating_prompts": [("features", r"App Store rating requests are MANDATORY.*?\(the features gate fails otherwise\)\.",
                        "Rating prompts are turned off (rating_prompts option): no RatingPolicy, no review request anywhere.")],
    "onboarding_quiz": [("features", r"Replace the placeholder onboarding questions \(≥5 questions, spec screen count, nothing preselected\),",
                         "Adapt the short intro screens (the quiz is turned off: no questions, spec screen count),")],
    "offer_paywall": [("iap", r", trial-less yearly\.offer", ""), ("iap", r"offerings default\+offer", "offering default")],
    "sign_in_with_apple": [("backend", r"Anonymous auth \+ Sign in with Apple linking\.",
                            "Anonymous auth only (Sign in with Apple is turned off).")],
}


def _apply_option_edits(app_dir: str | Path, stage: str, text: str) -> str:
    from . import options as options_mod
    for oid, edits in OPTION_OFF_EDITS.items():
        off = options_mod.is_off(app_dir, oid) or (oid == "offer_paywall" and options_mod.is_off(app_dir, "hard_paywall"))
        if not off:
            continue
        for st, pattern, repl in edits:
            if st == stage:
                text = re.sub(pattern, repl, text, flags=re.S)
    return text


def _ai_enabled(app_dir: str | Path) -> bool:
    from . import spec as spec_mod
    p = Path(app_dir).expanduser() / spec_mod.SPEC_FILE
    if not p.exists():
        return True
    try:
        return spec_mod.ai_enabled(json.loads(p.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return True


def stage_instruction(app_dir: str | Path, stage: str) -> str:
    """STAGE_INSTRUCTIONS, with the non-AI variant when app.spec.json has ai.enabled=false, or an n/a
    note when the stage's service is disabled."""
    from . import gates
    off = gates.stage_disabled_service(stage)
    if off:
        return (f"(n/a — the '{off}' service is disabled) Skip this stage: pipeline_mark(stage=\"{stage}\") "
                "records it as done (its gate reports skipped). Enable the service with "
                f"`appfactory services enable {off}` to run it.")
    from . import options as options_mod
    opt = options_mod.stage_disabled_option(app_dir, stage)
    if opt:
        return (f"(n/a — the user turned off the '{opt}' run option) Skip this stage: "
                f"pipeline_mark(stage=\"{stage}\") records it as done (its gate reports skipped).")
    if stage in AI_OFF_INSTRUCTIONS and not _ai_enabled(app_dir):
        return _apply_option_edits(app_dir, stage, AI_OFF_INSTRUCTIONS[stage])
    return _apply_option_edits(app_dir, stage, STAGE_INSTRUCTIONS.get(stage, ""))


def require_done(app_dir: str | Path, stage: str) -> dict[str, Any] | None:
    """Gate: return an error unless the stage is 'done' (None = passed)."""
    data = load(app_dir)
    if data is None:
        return {"ok": False, "error": "no manifest (run app_scaffold first)"}
    if data["stages"].get(stage) != "done":
        return {"ok": False, "error": f"stage '{stage}' is not complete; finish it first.",
                "hint": stage_instruction(app_dir, stage)}
    return None


def validate(app_dir: str | Path, stage: str) -> dict[str, Any]:
    """Run a stage's gate WITHOUT changing the manifest. For the orchestrator/debugging."""
    if stage not in STAGES:
        return {"ok": False, "error": f"unknown stage: {stage}"}
    from . import gates
    return gates.validate_stage(app_dir, stage)


# ---- ASO stage (mandatory) ----
def aso_run(app_dir: str | Path) -> dict[str, Any]:
    """Start the ASO stage: outputs scaffold + the skill instruction for Claude."""
    data = load(app_dir)
    if data is None:
        return {"ok": False, "error": "no manifest"}
    scaf = aso.scaffold_outputs(data["app"], data["dir"])
    mark(app_dir, "aso", "in_progress")
    return {
        "ok": True,
        "outputs": scaf,
        "instruction": (
            "Run the `aso` skill NOW. Use aso_fetch_competitors and aso_top_grossing for "
            "competitor data. Fill outputs/<App>/02-metadata/apple-metadata.md for every store "
            "locale, ASO-optimized and within the character limits. Then call aso_complete."
        ),
    }


def aso_complete(app_dir: str | Path) -> dict[str, Any]:
    """Validate the ASO output; if it passes, mark 'aso' done (opens the gate)."""
    data = load(app_dir)
    if data is None:
        return {"ok": False, "error": "no manifest"}
    chk = aso.validate_metadata(data["app"], data["dir"])
    if not chk.get("ok"):
        return {"ok": False, "error": "ASO metadata validation failed — apple-metadata.md is incomplete or over a limit.",
                "detail": chk}
    mark(app_dir, "aso", "done")
    return {"ok": True, "message": "ASO complete; the metadata/deliver gates are open.", "locales": chk.get("locales")}
