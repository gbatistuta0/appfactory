// GENERATED from app.spec.json by appfactory (supabase.render_backend). Do not edit by hand:
// change app.spec.json and re-render. The values below are the factory defaults.

/** App display name (legal page titles, logs). */
export const APP_NAME = "__DISPLAY_NAME__";

/** In-app languages (spec.locales.app). The first one is the fallback. */
export const SUPPORTED_LOCALES = ["en", "es", "pt-BR", "de", "fr", "tr"] as const;

/** RevenueCat placement ids (spec.placements); the backend returns them in 402/429 bodies. */
export const PLACEMENTS = {
  freeUsed: "free_scan_used",
  dailyCap: "daily_cap",
} as const;
