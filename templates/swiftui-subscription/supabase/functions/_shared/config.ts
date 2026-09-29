// config.ts — every tunable of the AI pipeline comes from the environment (Supabase secrets), so
// switching model, reasoning effort or quotas never needs a code change. The factory writes these
// secrets from app.spec.json (spec.ai + spec.usage + spec.consent) in backend_deploy.

export interface Config {
  falKey: string;
  model: string;                    // OpenRouter model id served through fal (spec.ai.model)
  fallbackModel: string | null;     // tried once when the primary fails or returns unusable output
  reasoning: string;                // none | minimal | low | medium | high (mapped per model family)
  timeoutMs: number;                // per model call
  freeLifetimeScans: number;        // non-subscriber: successful analyses per identity, lifetime (0 or 1)
  freeModes: Array<"photo" | "text">; // modes the free analysis may be used in (FREE_MODES, default photo)
  photoDailyLimit: number;          // subscriber: successful photo analyses per local calendar day
  textDailyLimit: number;           // subscriber: successful text analyses per local calendar day
  freeAttemptLimit: number;         // non-subscriber: billed model calls per rolling 24 h (abuse backstop)
  hardAttemptLimit: number;         // subscriber: billed model calls per rolling 24 h (abuse backstop)
  maxImageBytes: number;
  entitlementGraceMs: number;       // max entitlement cache TTL (re-check interval); never beyond access end
  requireConsent: boolean;          // spec.consent.health: 403 consent_required until profiles.consent_health_at
  rcProjectId: string;
  rcSecretKey: string;
}

function int(get: (k: string) => string | undefined, key: string, fallback: number): number {
  const raw = get(key);
  if (raw === undefined || raw === "") return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) throw new Error(`config: ${key} must be a non-negative number`);
  return Math.floor(n);
}

function bool(get: (k: string) => string | undefined, key: string, fallback: boolean): boolean {
  const raw = (get(key) ?? "").trim().toLowerCase();
  if (raw === "") return fallback;
  return raw === "1" || raw === "true" || raw === "yes";
}

function modes(raw: string): Array<"photo" | "text"> {
  const out = raw.split(",").map((m) => m.trim()).filter((m): m is "photo" | "text" => m === "photo" || m === "text");
  return [...new Set(out)];
}

export function loadConfig(get: (k: string) => string | undefined = (k) => Deno.env.get(k)): Config {
  const fallback = get("AI_FALLBACK_MODEL");
  return {
    falKey: get("FAL_KEY") ?? "",
    model: get("AI_MODEL") || "google/gemini-3.6-flash",
    // Unset → default fallback; empty string or "none" → no fallback.
    fallbackModel: fallback === undefined ? "google/gemini-3.8-flash" : (fallback && fallback !== "none" ? fallback : null),
    reasoning: get("AI_REASONING") || "minimal",
    timeoutMs: int(get, "AI_TIMEOUT_MS", 25_000),
    freeLifetimeScans: Math.min(1, int(get, "FREE_LIFETIME_SCANS", 1)),
    freeModes: modes(get("FREE_MODES") || "photo"),
    photoDailyLimit: int(get, "PHOTO_DAILY_LIMIT", 12),
    textDailyLimit: int(get, "TEXT_DAILY_LIMIT", 20),
    freeAttemptLimit: int(get, "FREE_ATTEMPT_LIMIT", 5),
    hardAttemptLimit: int(get, "HARD_ATTEMPT_LIMIT", 60),
    maxImageBytes: int(get, "MAX_IMAGE_BYTES", 1_500_000),
    entitlementGraceMs: int(get, "ENTITLEMENT_GRACE_HOURS", 72) * 3_600_000,
    requireConsent: bool(get, "REQUIRE_CONSENT", false),
    rcProjectId: get("RC_PROJECT_ID") ?? "",
    rcSecretKey: get("RC_SECRET_KEY") ?? "",
  };
}
