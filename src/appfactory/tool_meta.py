"""MCP metadata for the tools registered in server.py: parameter descriptions and behaviour annotations.

Kept out of server.py so tool bodies stay readable. `describe_signature` and `annotations_for` are applied by
the `@tool` wrapper. A key `"tool_name.param"` in PARAMS overrides the generic `"param"` entry.
"""
from __future__ import annotations

import inspect
import typing
from typing import Annotated, Any, Callable

from pydantic import Field

_PATH = "Absolute path to the app project directory (contains app.spec.json), e.g. /Users/me/Apps/MyApp."
_APPROVAL = ("Approval id from a previous approval_required refusal; omit on the first call. The human approves "
             "out-of-band with `appfactory approve <id>`, then call again with the same arguments and this id.")
_DRY = "If true (default) nothing is changed or sent and the exact plan/command is returned; false performs the live action."
_COUNTRY = "Two-letter App Store storefront code, lowercase, e.g. 'us', 'gb', 'de'."

PARAMS: dict[str, str] = {
    # shared
    "app_dir": _PATH,
    "approval_id": _APPROVAL,
    "dry_run": _DRY,
    "bundle_id": "App bundle identifier in reverse-DNS form, e.g. com.example.app.",
    "country": _COUNTRY,
    "project": "Path to the .xcodeproj or .xcworkspace to build, e.g. /path/App/App.xcodeproj.",
    "scheme": "Xcode scheme name to build, e.g. 'MyApp'.",
    "udid": "Simulator UDID from build_list_simulators, e.g. 'A1B2C3D4-...'.",
    "term": "Search term or seed keyword, e.g. 'habit tracker'.",
    "stage": "Pipeline stage id, e.g. 'aso', 'screenshots', 'features' (see pipeline_status for the list).",
    "app_id": "App Store Connect app id (numeric Apple id, e.g. '1234567890'); for aso_competitor_iap the iTunes trackId.",
    "group_id": "App Store Connect subscription group id.",
    "ref": "Supabase project ref (20-char id from supabase_list_projects, e.g. 'abcdefghijklmnopqrst').",
    "limit": "Maximum number of results to return.",
    "genre": "App Store category name (e.g. 'photo_video', 'productivity', 'health') or numeric genre id; omit for all/inferred.",
    "locales": "List of locale codes, e.g. ['en-US', 'de-DE']; omit for the default set.",
    "skip_options_check": "If true, do not require run_options_save to have been called first. Default false.",
    "marketing_dir": "Path to the app's marketing/ directory.",
    "overwrite": "If true, replace files that already exist; default false refuses to overwrite.",
    "repo": "GitHub repository as 'owner/name', e.g. 'octocat/my-app'.",
    "value": "Value to store.",
    "mode": "Operation mode.",
    "copyright": "Copyright line for the store listing, e.g. '2026 Example Ltd'; falls back to the config 'copyright' key.",
    "support_email": "Public support email address.",
    "sub_id": "App Store Connect subscription id.",
    "period": "Subscription period enum: ONE_WEEK, ONE_MONTH, TWO_MONTHS, THREE_MONTHS, SIX_MONTHS or ONE_YEAR.",
    "locale": "Locale code, e.g. 'en-US', 'de-DE'.",
    "out_path": "Output file path (PNG).",
    "device_name": "Simulator device name, e.g. 'iPhone 16'.",
    "archive_path": "Path to the .xcarchive, e.g. build/App.xcarchive.",
    "dest_dir": "Destination directory.",
    "message": "Free-text message.",
    "weekly_credits": "Credits granted per week on the weekly plan (integer).",
    "source_md": "Path to apple-metadata.md.",
    "countries": "List of two-letter storefront codes, e.g. ['us', 'gb', 'de']; omit for the default set.",
    "apple_cut": "Apple's commission as a fraction: 0.15 (Small Business Program, default) or 0.30.",
    "base_dir": "Directory that contains (or will contain) the outputs/<App>/ folder.",
    "concept": "Short concept description of the app used to write the image prompt, e.g. 'AI pet portrait maker'.",
    "allow_external_generator": "Must be true to allow the paid fal.ai image generator; default false refuses.",
    "project_ref": "Supabase project ref to deploy to.",
    "states": "Mascot pose/state names, e.g. ['idle', 'happy']; omit for all states.",
    # setup / config
    "enable": "Service ids to turn on, e.g. ['apple', 'supabase', 'revenuecat', 'github', 'firebase', 'xcode', 'maestro', 'design', 'ai', 'lottie'].",
    "disable": "Service ids to turn off (same ids as enable).",
    "key": "Non-secret config key, e.g. 'asc_key_id', 'team_id', 'support_email'.",
    "setup_approvals.mode": "Approvals mode; only 'required' is accepted here ('off' must be set by the human).",
    "services": "Service ids to collect credentials for; omit for every enabled service.",
    "asc_key_id": "App Store Connect API key id (10 characters).",
    "asc_issuer_id": "App Store Connect API issuer id (UUID).",
    "asc_key_filepath": "Path to the App Store Connect .p8 private key file.",
    "team_id": "Apple Developer Team id (10 characters).",
    "apple_id": "Apple ID email of the developer account (used by fastlane produce only).",
    "legal_controller": "Legal entity name shown as data controller in the privacy policy.",
    "asc_finance_key_id": "Key id of a Finance-role App Store Connect API key (for sales reports).",
    "asc_finance_key_filepath": "Path to the Finance-role .p8 key file.",
    "asc_vendor_number": "App Store Connect vendor number (sales reports).",
    # asc
    "identifier": "Bundle identifier to register, e.g. com.example.app.",
    "name": "Display name.",
    "apply_capabilities": "If true, also enable the spec's App ID capabilities (needs app_dir); false only checks them.",
    "app_name": "App name as shown on the App Store (globally unique, max 30 characters).",
    "asc_create_bundle_id.name": "Human-readable name of the bundle id in the developer portal, e.g. 'My App'.",
    "asc_create_app.app_name": "Single app name; prefer candidate_names. Converted to a one-element candidate list.",
    "asc_finalize_submission_requirements.app_name": "App name used to fill the generic App Review notes template.",
    "candidate_names": "Ordered candidate App Store names; the first one not already taken is used.",
    "sku": "Unique SKU string for the app record; omit to derive from the bundle id.",
    "primary_language": "Primary App Store language, e.g. 'en-US'.",
    "reference_name": "Internal reference name of the subscription group (not shown to users).",
    "asc_finalize_subscription.name": "Subscription display name shown to users (en-US).",
    "description": "Subscription description shown to users (en-US).",
    "usd_price": "USD base price as a decimal string, e.g. '49.99'.",
    "asc_finalize_subscription.period": "Ignored; kept for backward compatibility.",
    "intro": "Intro offer from the spec product, e.g. {\"type\": \"free\", \"duration\": \"P3D\"}; omit for offer products (no intro).",
    "contact_first": "App Review contact first name.",
    "contact_last": "App Review contact last name.",
    "contact_phone": "App Review contact phone in international format, e.g. '+14155550100'.",
    "contact_email": "App Review contact email; defaults to the config support_email.",
    "free": "If true (default) the app price is set to Free.",
    "review_notes": "Custom App Review notes; omit to fill the generic 7-item test-flow template.",
    "ai_services": "Short description of the AI services the app uses, inserted into the review notes.",
    "privacy_url": "Public privacy policy URL, e.g. https://example.com/privacy.",
    "terms_url": "Terms of Use/EULA URL; omit to use Apple's standard EULA.",
    "disclosure_by_locale": "Optional {locale: disclosure text} overriding the default subscription disclosure per language.",
    "usd_price_by_product": "Map of subscription productId to USD price string, e.g. {'com.example.app.yearly': '49.99'}.",
    "default_usd": "USD price string applied to subscriptions not listed in usd_price_by_product.",
    "asc_add_subscription_group_localization.name": "Subscription group display name shown to users.",
    "asc_create_subscription.name": "Internal reference name of the subscription product.",
    "items": "Map {locale: {name, description}} of subscription display copy per locale.",
    "name_by_locale": "Map {locale: group display name}.",
    "product_id": "Product identifier of the subscription, e.g. com.example.app.yearly.",
    "family_shareable": "Whether the subscription can be shared with family members; default false.",
    "report_date": "Sales report date YYYY-MM-DD; omit to use the latest available.",
    "days_back": "How many days back to search for the latest report (default 7).",
    # build / maestro
    "tags": "Comma-separated Maestro tag filter, e.g. 'smoke'; omit to run every flow.",
    "device": "Simulator UDID to run on; omit for the booted simulator.",
    "configuration": "Xcode build configuration, default 'Release'.",
    "export_dir": "Directory to write the exported .ipa into.",
    "export_options_plist": "Path to the ExportOptions.plist for xcodebuild -exportArchive.",
    # supabase
    "sql": "SQL to execute. Destructive statements (DROP, TRUNCATE, DELETE/UPDATE without WHERE) always need approval.",
    "supabase_set_secret.name": "Edge function secret name, e.g. 'FAL_KEY'.",
    "supabase_set_secret.value": "Secret value; written server-side and never echoed back.",
    "supabase_create_project.name": "Name of the new Supabase project.",
    "org_id": "Supabase organization id from supabase_list_orgs.",
    "region": "Supabase region code, e.g. 'us-east-1', 'eu-central-1'.",
    "db_pass": "Database password for the new project.",
    # scaffold / app
    "app_scaffold.name": "App name, e.g. 'PetPortrait'; used for the folder and target.",
    "display_name": "Name shown under the app icon; defaults to name.",
    "app_scaffold.dest_dir": "Directory to create the app folder in; omit for the default apps directory.",
    "spec": "Full app.spec.json as a dict, a dict of overrides on the defaults, or a path to an app.spec.json file.",
    "repo_name": "Name of the new private repository, e.g. 'my-app'.",
    "github_push.message": "Git commit message.",
    "preview_brief.message": "Optional extra direction appended to the brief.",
    "project_dir": "Path to the scaffolded app project directory.",
    "supabase_url": "Supabase project URL, e.g. https://abcd.supabase.co.",
    "supabase_anon_key": "Supabase anon (public) key.",
    "ai_proxy_url": "URL of the deployed AI proxy/edge function.",
    "posthog_key": "PostHog project API key.",
    "product_yearly": "Yearly subscription product id.",
    "product_weekly": "Weekly subscription product id.",
    "app_inject_config.privacy_url": "Public privacy policy URL.",
    "revenuecat_key": "RevenueCat public SDK key (appl_...).",
    "yearly_credits": "Credits granted per month on the yearly plan (default 15).",
    "app_inject_config.weekly_credits": "Credits granted per week on the weekly plan (default 10).",
    "credit_pack_small": "Credits in the small top-up pack (default 10).",
    "credit_pack_medium": "Credits in the medium top-up pack (default 30).",
    "credit_pack_large": "Credits in the large top-up pack (default 60).",
    "paywall_strategy": "'hard_only' (hard paywall only) or 'hard_and_offer' (default: plus a discounted offer paywall on dismiss).",
    "step_count": "Desired number of onboarding steps; recommended range 8-15 (default 12).",
    "slot": "Animation slot: 'loading', 'success', 'empty' or 'onboarding_hero'.",
    "primary_hex": "Primary palette color as hex, '#' optional, e.g. '006A63'.",
    "accent_hex": "Accent palette color as hex, '#' optional, e.g. 'FFB300'.",
    "keyword": "App-themed search keyword override, e.g. 'happy dog celebration'.",
    # metadata / aso / ideas
    "metadata_export.dest_dir": "Output directory for the per-locale .txt files, e.g. <app>/fastlane/metadata.",
    "metadata_export.source_md": "Path to apple-metadata.md to export.",
    "support_url": "Public support page URL.",
    "metadata_export.privacy_url": "Public privacy policy URL written to the metadata files.",
    "metadata_export.app_dir": "App directory; when given, export is refused until the ASO stage is complete.",
    "primary_category": "Primary App Store category id, e.g. 'PHOTO_AND_VIDEO'.",
    "secondary_category": "Secondary App Store category id, e.g. 'PRODUCTIVITY'.",
    "aso_check_name.name": "Candidate App Store app name to check.",
    "candidates": "Ordered candidate app names.",
    "aso_top_grossing.limit": "Number of chart entries to return (default 25).",
    "aso_fetch_competitors.limit": "Number of competitor apps to return (default 10).",
    "expand": "If true, append a-z to the seed to collect the full keyword universe; default false.",
    "genres": "Category names to sweep, e.g. ['health', 'productivity']; omit for all 24 charted categories.",
    "idea_harvest.limit": "Chart entries fetched per genre and storefront (default 100).",
    "newcomer_months": "Apps released within this many months count as rising newcomers (default 12).",
    "exclude_terms": "Name/seller substrings to drop from results (e.g. your own apps).",
    "feeds": "Chart feeds to use, e.g. ['topgrossing', 'topfree']; omit for both.",
    "max_results": "Maximum entries per result list (default 50).",
    "name_candidates": "Candidate app names; the first available one is reported.",
    "leaders": "Number of category leaders to profile with price ladders (default 3).",
    "weekly_price": "Weekly subscription price in USD (default 7.99).",
    "yearly_price": "Yearly subscription price in USD (default 49.99).",
    "aso_unit_economics.weekly_credits": "Credits per week on the weekly plan (default 10).",
    "yearly_monthly_credits": "Credits per month on the yearly plan (default 15).",
    "ai_cost_per_credit": "AI provider cost per credit in USD (default 0.003).",
    "aso_scaffold_outputs.app_name": "App name; creates outputs/<app_name>/.",
    "aso_validate_metadata.app_name": "App name whose outputs/<app_name>/02-metadata/apple-metadata.md is validated.",
    "aso_scaffold_outputs.locales": "Locale codes for the metadata skeleton; omit for the 32 default languages.",
    # icon / localize / pipeline / options
    "source": "Path to the 1024x1024 icon master, relative to the app dir (default 'design/icon.png').",
    "extra": "Extra prompt text appended to the concept.",
    "translations": "Map {english_key: {locale: translated value}} for the String Catalog.",
    "status": "New stage status: 'done', 'in_progress' or 'pending'.",
    "answers": "Map {option id: value} covering every option id returned by run_options.",
    "run_options.app_dir": "App directory to read current values from; omit before the app is scaffolded.",
    "run_options_save.app_dir": "App directory whose app.spec.json receives the answers; omit to save to the pending file used by app_scaffold.",
    "orchestrator_preflight.app_dir": "App directory; omit before the app is scaffolded.",
    "reason": "Why self-correction is exhausted (what failed).",
    "how_to_resolve": "What the human needs to do to unblock the stage.",
    # screenshots / preview / growth
    "screenshot_capture.locale": "App locale of the capture, e.g. 'en-US'; used as the output subfolder.",
    "screenshot_capture.name": "Screen name, used as the file name, e.g. 'paywall'.",
    "fastlane_screenshots_dir": "Path to fastlane/screenshots/ to sync branded images into.",
    "sample_prompt": "Prompt describing a sample output of the app (fills Result/Gallery screens).",
    "prompt": "Image generation prompt for the sample output.",
    "count": "Number of onboarding hero images to generate (default 11).",
    "slideshows": "List of {name, slides: [{text, image_prompt or image, cta}]} to render at 1080x1920.",
    "file": "Preview file path relative to the app dir, e.g. 'fastlane/app_previews/en-US/preview.mp4'.",
    "scores": "Scores 1-10 for keys hook, readability, motion, variety, brand, music.",
    "problems": "Up to 3 worst problems as [{t: seconds, issue: text}]; required while any score is under 8.",
    "replace": "If true, replace preview sets that already exist on App Store Connect.",
    "preview_upload.locales": "Locale codes to upload; omit for every locale in fastlane/app_previews/.",
    "themes": "List of {name, locale} Search Ads themes, one Custom Product Page each.",
    # signing / ai / rc
    "cert_id": "App Store Connect certificate id from signing_setup_distribution.",
    "signing_create_profile.name": "Provisioning profile name (default 'AppFactory AppStore').",
    "providers": "AI provider ids; default ['fal.ai'].",
    "daily_limit": "Per-user daily request cap for the legacy ai-proxy (default 20).",
    "v2_key": "RevenueCat secret API v2 key (sk_...); used for this call only.",
    "supabase_ref": "Supabase project ref that receives the RevenueCat secrets.",
    "env_suffix": "Suffix for secret names when several apps share one Supabase project, e.g. '_MYAPP'.",
    "set_secrets": "If true (default) also write the RevenueCat secrets to Supabase.",
    # backend / legal / store
    "values": "Map of placeholder name to text for product-specific legal placeholders.",
    "store_setup.mode": "'plan' (offline), 'check' (live reads, simulated writes, reports CONFLICT) or 'apply' (live writes, needs approval).",
    "target": "What to set up: 'capabilities', 'asc', 'rc' or 'all' (default).",
    "rc_apple_notification_url": "RevenueCat's Apple Server-to-Server notification URL, stored in app outputs.",
    "rc_project_id": "RevenueCat project id (proj...) if it already exists.",
    "cost_photo": "Measured AI cost in USD per photo call; omit to read from backend/eval/results.",
    "cost_text": "Measured AI cost in USD per text call; omit to read from backend/eval/results.",
    "storekit_path": "Path to a Configuration.storekit; omit for Resources/Configuration.storekit.",
    # design
    "write": "If true, save the skeleton to design/screens.json; default false only returns it.",
    "terms": "Search terms describing the app category, e.g. ['meditation', 'sleep sounds'].",
    "max_apps": "Maximum reference apps to download (default 16).",
    "screenshots_per_app": "Screenshots to download per reference app (default 6).",
    "project_id": "Claude Design project id from create_project.",
    "open_url": "The claude.ai/design link returned by render_preview (not the serve_url).",
    "serve_url": "Temporary serve_url from claude-design render_preview; used once, never stored.",
    "width": "Viewport width in CSS pixels, e.g. 1024 for the icon board or 440 for a store board.",
    "height": "Viewport height in CSS pixels, e.g. 1024 for the icon board or 956 for a store board.",
    "scale": "Device scale factor (default 1; use 3 for store boards).",
    "paths": "Explicit pose PNG paths; overrides the default <app>/design/mascot/<state>.png.",
    "source_dir": "Directory with approved pose PNGs; omit for <app>/design/mascot.",
    "sessions": "Names of the team sessions as {lead, ios, backend, store}.",
    "team_brief.repo": "GitHub repo 'owner/name' to reference in the briefs; optional.",
    "title": "Issue title in imperative form, e.g. 'Add offer paywall analytics'.",
    "labels": "Issue labels: one role label (ios, backend, store, lead, founder) plus next or later.",
    "body": "Issue body with what / why / done-when sections.",
    "github_issues_bootstrap.app_dir": "App directory; when given, the github_issues run option is read from its spec.",
    "github_issue_create.app_dir": "App directory; when given, the github_issues run option is read from its spec.",
}

# ---------- annotations ----------
READ_ONLY = {
    "setup_status", "config_doctor", "asc_token_check", "asc_list_apps", "asc_get_app", "env_doctor",
    "build_xcode_version", "build_list_simulators", "supabase_list_projects", "supabase_list_orgs",
    "metadata_check", "aso_check_name", "aso_find_available_name", "aso_fetch_competitors", "aso_top_grossing",
    "aso_search_hints", "aso_niche_score", "idea_harvest", "idea_evaluate", "aso_competitor_iap",
    "aso_unit_economics", "aso_validate_metadata", "pipeline_status", "pipeline_next", "pipeline_validate",
    "orchestrator_preflight", "orchestrator_next_action", "run_options", "onboarding_plan", "preview_check",
    "deliver_screenshots_audit", "legal_check", "legal_verify", "metadata_listing_check", "asc_sbp_check",
    "storekit_parity", "design_research_brief_template", "design_research_check", "design_upload_status",
    "playbook", "ai_configure",
}
# Local writes that give the same result when repeated with the same arguments.
IDEMPOTENT_WRITES = {
    "setup_services", "setup_set", "setup_approvals", "config_set", "app_inject_config", "animation_fetch_recolor",
    "metadata_export", "aso_scaffold_outputs", "aso_run", "aso_complete", "icon_install", "localize_apply",
    "pipeline_mark", "run_options_save", "screenshot_apply_layout", "screenshot_sync", "screenshot_brand",
    "screenshot_capture", "backend_render", "legal_render", "metadata_render_listing", "pricing_unit_economics",
    "storekit_generate", "app_sync_spec", "design_screens_skeleton", "design_generate", "design_record_upload",
    "mascot_blink", "mascot_assets", "team_brief", "preview_brief", "preview_review_sheets", "preview_review_log",
    "design_research_collect", "design_export_png", "build_boot_sim", "build_screenshot", "supabase_get_keys",
    "orchestrator_needs_human", "growth_build_slideshows",
    # approval-gated but idempotent on the remote side
    "asc_finalize_subscription", "asc_append_subscription_disclosure", "asc_ensure_subscription_prices",
    "asc_add_subscription_group_localization", "asc_localize_subscription", "asc_localize_group",
    "asc_finalize_submission_requirements", "deliver_metadata", "deliver_screenshots",
    "deliver_subscription_review_screenshots", "preview_upload", "store_setup", "revenuecat_setup",
    "backend_deploy", "ai_deploy_proxy", "github_issues_bootstrap", "supabase_set_secret",
}
# Local-only even though a service gate exists (nothing leaves the machine) or no gate exists but the network is used.
_NETWORK_SERVICES = {"apple", "supabase", "revenuecat", "github", "firebase", "ai", "lottie"}
_LOCAL_DESPITE_GATE = {"ai_configure"}
_NETWORK_UNGATED = {
    "aso_check_name", "aso_find_available_name", "aso_fetch_competitors", "aso_top_grossing", "aso_search_hints",
    "aso_niche_score", "aso_competitor_iap", "idea_harvest", "idea_evaluate", "legal_verify",
    "design_research_collect", "growth_build_slideshows", "github_issues_bootstrap", "github_issue_create",
}
_ACRONYMS = {"asc": "ASC", "aso": "ASO", "ai": "AI", "sql": "SQL", "ipa": "IPA", "png": "PNG", "cpp": "CPP",
             "iap": "IAP", "sbp": "SBP", "rc": "RevenueCat", "github": "GitHub", "testflight": "TestFlight",
             "supabase": "Supabase", "revenuecat": "RevenueCat", "storekit": "StoreKit", "sim": "Simulator",
             "ios": "iOS", "id": "ID", "url": "URL", "api": "API", "ui": "UI", "gui": "GUI", "env": "Environment",
             "xcode": "Xcode", "sdk": "SDK", "cli": "CLI"}


def title_for(name: str) -> str:
    return " ".join(_ACRONYMS.get(w, w.capitalize()) for w in name.split("_"))


def annotations_for(name: str, params: typing.Iterable[str], services: tuple[str, ...]) -> dict[str, Any]:
    """MCP ToolAnnotations derived from the tool's name, parameters and service gate."""
    read_only = name in READ_ONLY
    gated_write = "approval_id" in set(params)  # human-approval mechanism = live write
    open_world = (bool(set(services) & _NETWORK_SERVICES) or name in _NETWORK_UNGATED) and name not in _LOCAL_DESPITE_GATE
    return {
        "title": title_for(name),
        "readOnlyHint": read_only,
        "destructiveHint": gated_write and not read_only,
        "idempotentHint": read_only or name in IDEMPOTENT_WRITES,
        "openWorldHint": open_world,
    }


def param_description(tool_name: str, param: str) -> str | None:
    return PARAMS.get(f"{tool_name}.{param}") or PARAMS.get(param)


def describe_signature(fn: Callable[..., Any]) -> inspect.Signature:
    """fn's signature with every parameter annotated as Annotated[T, Field(description=...)]."""
    hints = typing.get_type_hints(fn, include_extras=True)
    sig = inspect.signature(fn)
    params = []
    for p in sig.parameters.values():
        desc = param_description(fn.__name__, p.name)
        ann = hints.get(p.name, Any)
        if desc:
            ann = Annotated[ann, Field(description=desc)]
        params.append(p.replace(annotation=ann))
    return sig.replace(parameters=params, return_annotation=hints.get("return", sig.return_annotation))
