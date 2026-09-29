// analyze — photo or short text → the app's AI result (see backend/CONTRACT.md).
//
// Order of operations (each step can end the request):
//   1. auth        anonymous (or Apple-linked) Supabase JWT → user id (== RevenueCat app_user_id)  401
//   2. validate    mode, image/text, locale, app options (_shared/analysis.ts)                    400/413/415
//   3. consent     explicit consent on the profile, when REQUIRE_CONSENT (spec.consent.health)     403
//   4. entitle     subscriber? (cached RevenueCat pull; trial and sandbox count)                   503 if unknown
//   5. gate        free analysis / daily caps / attempt backstop                                   402/429
//   6. analyze     primary model, then the fallback model once on failure or bad output            502
//   7. record      ai_usage row for every billed call; only status=ok counts as usage
//   8. respond     normalized result + remaining quota                                             200/422
// A failed analysis never costs the user a scan: usage is written as ok only after success.
import {
  MAX_OUTPUT_TOKENS, OUTPUT_SCHEMA, type ParsedOutput, parseOutput, SCHEMA_NAME, systemPrompt, userPrompt,
  validateOptions, type AppOptions,
} from "../_shared/analysis.ts";
import { PLACEMENTS } from "../_shared/app.gen.ts";
import type { Config } from "../_shared/config.ts";
import { resolveEntitlement } from "../_shared/entitlement.ts";
import { bearer, checkImage, json } from "../_shared/http.ts";
import type { LlmClient, LlmResult } from "../_shared/llm.ts";
import { languageName, languageRule, normalizeLocale } from "../_shared/locale.ts";
import type { RcLookup } from "../_shared/rc.ts";
import type { DenialReason, Mode, Store, Tier, UsageStatus } from "../_shared/store.ts";
import { consumeOne, gate, usageSummary, WINDOW_MS } from "../_shared/usage.ts";

export interface Deps {
  cfg: Config;
  store: Store;
  llm: LlmClient;
  rc: RcLookup;
  userIdFromJwt: (jwt: string) => Promise<string | null>;
  now: () => number;
  log?: (msg: string, data?: Record<string, unknown>) => void;
}

const MAX_NOTE = 280;
const MAX_TEXT = 500;

interface ValidRequest {
  mode: Mode;
  image: { mime: string; base64: string } | null;
  note: string | null;
  text: string | null;
  locale: ReturnType<typeof normalizeLocale>;
  options: AppOptions;
}

function bad(message: string, status = 400, error = "invalid_request"): Response {
  return json({ error, message }, status);
}

function validate(body: unknown, cfg: Config): ValidRequest | Response {
  if (!body || typeof body !== "object" || Array.isArray(body)) return bad("body must be a JSON object");
  const b = body as Record<string, unknown>;
  const mode = b.mode;
  if (mode !== "photo" && mode !== "text") return bad('mode must be "photo" or "text"');
  const options = validateOptions(b);
  if (typeof options === "string") return bad(options);
  const locale = normalizeLocale(b.locale);

  if (mode === "photo") {
    const img = b.image as Record<string, unknown> | undefined;
    const check = checkImage(img?.data, cfg.maxImageBytes);
    if (!check.ok) return bad(check.message, check.status, check.error);
    let note: string | null = null;
    if (b.note !== undefined && b.note !== null) {
      if (typeof b.note !== "string") return bad("note must be a string");
      note = b.note.trim() || null;
      if (note && note.length > MAX_NOTE) return bad(`note must be at most ${MAX_NOTE} characters`);
    }
    return { mode, image: { mime: check.mime, base64: check.base64 }, note, text: null, locale, options };
  }

  const text = typeof b.text === "string" ? b.text.trim() : "";
  if (!text) return bad("text is required in text mode");
  if (text.length > MAX_TEXT) return bad(`text must be at most ${MAX_TEXT} characters`);
  return { mode, image: null, note: null, text, locale, options };
}

function usageStatus(result: LlmResult, parsed: ParsedOutput | null): UsageStatus {
  if (!result.ok) return "provider_error";
  if (parsed?.kind === "not_applicable") return "not_applicable";
  if (parsed?.kind === "result") return "ok";
  return "invalid_output";
}

export function createHandler(deps: Deps): (req: Request) => Promise<Response> {
  const { cfg, store, llm, rc, now } = deps;
  const log = deps.log ?? ((msg, data) => console.log(JSON.stringify({ fn: "analyze", msg, ...data })));

  return async (req) => {
    if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

    // 1. auth
    const jwt = bearer(req);
    const userId = jwt ? await deps.userIdFromJwt(jwt) : null;
    if (!userId) return json({ error: "unauthorized" }, 401);

    // 2. validate
    let body: unknown;
    try {
      body = await req.json();
    } catch {
      return bad("body is not valid JSON");
    }
    const input = validate(body, cfg);
    if (input instanceof Response) return input;

    // A refused request is recorded for analytics; that write must never change the answer.
    const deny = async (status: number, payload: Record<string, unknown>, reason: DenialReason, tier: Tier | null) => {
      try {
        await store.insertDenial({ user_id: userId, mode: input.mode, tier, reason });
      } catch (e) {
        log("denial_log_failed", { userId, error: (e as Error).message });
      }
      return json(payload, status);
    };

    try {
      // 3. consent. Checked before anything that costs money or calls RevenueCat.
      if (cfg.requireConsent && !(await store.hasConsent(userId))) {
        return await deny(403, { error: "consent_required" }, "consent_required", null);
      }

      // 4. entitlement. If RevenueCat is down and the cache has no answer, a user who still has the
      //    free analysis proceeds as free; anyone else gets a retryable 503 (never a paywall — they
      //    may well have paid).
      const nowMs = now();
      const ent = await resolveEntitlement(store, rc, userId, nowMs, cfg.entitlementGraceMs);
      const premium = ent.tier === "premium";
      const summary = await usageSummary(store, cfg, userId, premium);
      if (ent.tier === "unknown") {
        log("entitlement_unknown", { userId, error: ent.error });
        if (!(summary.free_scan_available && summary[input.mode].limit > 0)) {
          return await deny(503, { error: "entitlement_unavailable", retryable: true }, "entitlement_unavailable", null);
        }
      }
      const tier: Tier = premium ? "premium" : "free";

      // 5. gate
      const attempts = await store.usageSince(userId, new Date(nowMs - WINDOW_MS).toISOString(), { okOnly: false });
      const g = gate(summary, input.mode, attempts, cfg);
      if (!g.allow) return await deny(g.status, g.body, (g.body.reason ?? g.body.error) as DenialReason, tier);

      // 6 + 7. analyze (primary, then fallback once) and record every billed call
      const models = [...new Set([cfg.model, cfg.fallbackModel].filter((m): m is string => !!m))];
      const system = systemPrompt(languageName(input.locale), languageRule(input.locale));
      const user = userPrompt({
        mode: input.mode, locale: input.locale, note: input.note, text: input.text, options: input.options,
      });

      for (const model of models) {
        const result = await llm({
          model, system, userText: user, image: input.image,
          schema: OUTPUT_SCHEMA as unknown as Record<string, unknown>, schemaName: SCHEMA_NAME,
          reasoning: cfg.reasoning, maxTokens: MAX_OUTPUT_TOKENS, timeoutMs: cfg.timeoutMs,
        });
        const parsed = result.ok ? parseOutput(result.content) : null;
        const status = usageStatus(result, parsed);
        const usage = result.usage;
        const row = {
          user_id: userId, mode: input.mode, tier, status, model, locale: input.locale,
          input_tokens: usage?.inputTokens ?? null, output_tokens: usage?.outputTokens ?? null,
          thinking_tokens: usage?.thinkingTokens ?? null, cost_usd: usage?.costUsd ?? null,
          latency_ms: result.latencyMs,
          result: parsed?.kind === "result" ? parsed.result : null,
        };

        if (status !== "ok") {
          await store.insertUsage(row);
          log("attempt_failed", {
            userId, model, status,
            detail: result.ok ? (parsed?.kind === "invalid" ? parsed.reason : parsed?.kind) : `${result.kind} ${result.status ?? ""} ${result.message}`,
          });
          if (status === "not_applicable") return json({ error: "not_applicable", usage: summary }, 422);
          continue;
        }

        const id = await store.insertUsage(row);
        if (id === "free_scan_taken") {
          // A concurrent request consumed the free analysis first; withhold this result.
          return await deny(
            402, { error: "paywall_required", reason: "free_scan_used", placement: PLACEMENTS.freeUsed },
            "free_scan_used", tier,
          );
        }
        const ok = parsed as Extract<ParsedOutput, { kind: "result" }>;
        return json({
          analysis_id: id,
          mode: input.mode,
          locale: input.locale,
          result: ok.result,
          usage: consumeOne(summary, input.mode),
        });
      }

      return json({ error: "analysis_failed", retryable: true }, 502);
    } catch (e) {
      log("internal_error", { userId, error: (e as Error).message });
      return json({ error: "internal_error", retryable: true }, 500);
    }
  };
}
