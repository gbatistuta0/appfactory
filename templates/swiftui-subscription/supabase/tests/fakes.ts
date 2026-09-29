// fakes.ts — in-memory stand-ins for the database, the model and RevenueCat.
import { type Config, loadConfig } from "../functions/_shared/config.ts";
import type { LlmClient, LlmRequest, LlmResult } from "../functions/_shared/llm.ts";
import type { RcLookup, RcSubscription } from "../functions/_shared/rc.ts";
import type { CapDay, DenialInsert, EntitlementRow, Store, UsageInsert } from "../functions/_shared/store.ts";

export const T0 = Date.parse("2026-09-24T12:00:00Z");

export function testConfig(overrides: Record<string, string> = {}): Config {
  const env: Record<string, string> = {
    FAL_KEY: "test-key",
    AI_MODEL: "google/gemini-3.6-flash",
    AI_FALLBACK_MODEL: "google/gemini-3.8-flash",
    ...overrides,
  };
  return loadConfig((k) => env[k]);
}

export class MemoryStore implements Store {
  entitlements = new Map<string, EntitlementRow>();
  usage: Array<UsageInsert & { id: number; created_at: string }> = [];
  denials: DenialInsert[] = [];
  /** Users without consent (everyone else has consented). */
  noConsent = new Set<string>();
  /** Cap day override; default: the UTC calendar day of the clock. */
  day: CapDay | null = null;
  /** Make every read throw (store outage). */
  broken = false;
  clock: () => number;

  constructor(clock: () => number = () => T0) {
    this.clock = clock;
  }

  private check() {
    if (this.broken) throw new Error("db down");
  }

  getEntitlement(userId: string) {
    this.check();
    return Promise.resolve(this.entitlements.get(userId) ?? null);
  }
  putEntitlement(userId: string, row: EntitlementRow) {
    this.entitlements.set(userId, { ...row });
    return Promise.resolve();
  }
  freeScanUsed(userId: string) {
    return Promise.resolve(this.usage.some((u) => u.user_id === userId && u.tier === "free" && u.status === "ok"));
  }
  capDay(_userId: string): Promise<CapDay> {
    if (this.day) return Promise.resolve(this.day);
    const start = Math.floor(this.clock() / 86_400_000) * 86_400_000;
    return Promise.resolve({
      timezone: "UTC",
      day_start: new Date(start).toISOString(),
      resets_at: new Date(start + 86_400_000).toISOString(),
    });
  }
  hasConsent(userId: string) {
    this.check();
    return Promise.resolve(!this.noConsent.has(userId));
  }
  usageSince(userId: string, sinceIso: string, f: { mode?: "photo" | "text"; okOnly: boolean }) {
    const rows = this.usage
      .filter((u) => u.user_id === userId && u.created_at >= sinceIso)
      .filter((u) => !f.mode || u.mode === f.mode)
      .filter((u) => !f.okOnly || u.status === "ok")
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
    return Promise.resolve({ count: rows.length, oldest: rows[0]?.created_at ?? null });
  }
  insertUsage(row: UsageInsert) {
    if (row.tier === "free" && row.status === "ok" &&
      this.usage.some((u) => u.user_id === row.user_id && u.tier === "free" && u.status === "ok")) {
      return Promise.resolve("free_scan_taken" as const);
    }
    const id = this.usage.length + 1;
    this.usage.push({ ...row, id, created_at: new Date(this.clock()).toISOString() });
    return Promise.resolve(id);
  }
  insertDenial(row: DenialInsert) {
    this.denials.push(row);
    return Promise.resolve();
  }
  /** Seed past usage rows. */
  seed(userId: string, n: number, opts: Partial<UsageInsert> & { atMs?: number } = {}) {
    for (let i = 0; i < n; i++) {
      this.usage.push({
        user_id: userId, mode: "photo", tier: "premium", status: "ok", model: "m", locale: "en",
        input_tokens: null, output_tokens: null, thinking_tokens: null, cost_usd: null, latency_ms: null,
        result: null, ...opts, id: this.usage.length + 1,
        created_at: new Date((opts.atMs ?? T0 - 3_600_000) + i * 1000).toISOString(),
      });
    }
  }
}

export const GOOD_OUTPUT = JSON.stringify({
  is_applicable: true,
  title: "Sunset over the sea",
  summary: "  A warm orange sunset   over calm water. ",
  tags: ["sunset", "sea", "orange", "calm", "evening", "extra"],
  confidence: 0.82,
});

export const NOT_APPLICABLE_OUTPUT = JSON.stringify({
  is_applicable: false, title: "", summary: "", tags: [], confidence: 0.9,
});

export function okResult(content: string, model = "google/gemini-3.6-flash"): LlmResult {
  return {
    ok: true, model, content, finishReason: "stop", latencyMs: 900,
    usage: { inputTokens: 2100, outputTokens: 420, thinkingTokens: 0, costUsd: 0.0031 },
  };
}

export function errorResult(model: string, status = 503): LlmResult {
  return { ok: false, model, kind: "http", status, message: "upstream unavailable", usage: null, latencyMs: 300 };
}

/** Scripted model: returns the queued results in order and records every request. */
export function scriptedLlm(results: LlmResult[]): LlmClient & { calls: LlmRequest[] } {
  const calls: LlmRequest[] = [];
  const fn = ((req: LlmRequest) => {
    calls.push(req);
    const next = results.shift();
    if (!next) throw new Error("scriptedLlm: no more results");
    return Promise.resolve({ ...next, model: req.model });
  }) as LlmClient & { calls: LlmRequest[] };
  fn.calls = calls;
  return fn;
}

export function rcReturning(sub: RcSubscription | null | Error): RcLookup & { calls: number } {
  const fn = Object.assign(
    (_userId: string): Promise<RcSubscription | null> => {
      fn.calls++;
      return sub instanceof Error ? Promise.reject(sub) : Promise.resolve(sub);
    },
    { calls: 0 },
  );
  return fn;
}

export const ACTIVE_SUB: RcSubscription = {
  productId: "com.example.app.yearly",
  environment: "production",
  status: "active",
  expiresMs: T0 + 30 * 86_400_000,
};

// Smallest valid JPEG header followed by filler — enough for the magic-byte check.
export const JPEG_B64 = btoa(String.fromCharCode(0xff, 0xd8, 0xff, 0xe0, ...new Array(60).fill(0x41)));
export const PNG_B64 = btoa(String.fromCharCode(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...new Array(56).fill(0)));
