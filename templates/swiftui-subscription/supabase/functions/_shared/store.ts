// store.ts — the edge functions' only view of the database (service role). An interface so the
// handler logic is testable with an in-memory fake; the Supabase implementation is kept thin.
import type { SupabaseClient } from "jsr:@supabase/supabase-js@2";

export type Mode = "photo" | "text";
export type Tier = "free" | "premium";
export type UsageStatus = "ok" | "not_applicable" | "invalid_output" | "provider_error";

export interface EntitlementRow {
  plan: "none" | "premium";
  environment: "production" | "sandbox" | null;
  product_id: string | null;
  valid_until: string | null;
}

export interface UsageInsert {
  user_id: string;
  mode: Mode;
  tier: Tier;
  status: UsageStatus;
  model: string | null;
  locale: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  thinking_tokens: number | null;
  cost_usd: number | null;
  latency_ms: number | null;
  result: unknown;
}

/** The caller's current cap day (UTC instants). */
export interface CapDay {
  timezone: string;
  day_start: string;
  resets_at: string;
}

export type DenialReason =
  | "free_scan_used" | "subscription_required" | "daily_cap_reached" | "too_many_attempts"
  | "entitlement_unavailable" | "consent_required";

export interface DenialInsert {
  user_id: string;
  mode: Mode;
  tier: Tier | null;
  reason: DenialReason;
}

export interface UsageWindow {
  count: number;
  oldest: string | null;   // created_at of the oldest counted row (for resets_at)
}

export interface Store {
  getEntitlement(userId: string): Promise<EntitlementRow | null>;
  putEntitlement(userId: string, row: EntitlementRow): Promise<void>;
  freeScanUsed(userId: string): Promise<boolean>;
  /** Local calendar day for the subscriber caps (applies the timezone-change guard). */
  capDay(userId: string): Promise<CapDay>;
  /** Has the user given explicit consent (profiles.consent_health_at)? */
  hasConsent(userId: string): Promise<boolean>;
  /** Rows since `sinceIso`. okOnly counts successful analyses; otherwise every billed call. */
  usageSince(userId: string, sinceIso: string, filter: { mode?: Mode; okOnly: boolean }): Promise<UsageWindow>;
  /** Returns the new row id, or "free_scan_taken" if the one-free-scan index rejected it. */
  insertUsage(row: UsageInsert): Promise<number | "free_scan_taken">;
  /** A request refused before the model call (analytics only). */
  insertDenial(row: DenialInsert): Promise<void>;
}

export function supabaseStore(supa: SupabaseClient): Store {
  return {
    async getEntitlement(userId) {
      const { data, error } = await supa.from("entitlements")
        .select("plan, environment, product_id, valid_until")
        .eq("user_id", userId).maybeSingle();
      if (error) throw new Error(`entitlements read: ${error.message}`);
      return data as EntitlementRow | null;
    },

    async putEntitlement(userId, row) {
      const { error } = await supa.from("entitlements")
        .upsert({ user_id: userId, ...row, checked_at: new Date().toISOString() }, { onConflict: "user_id" });
      if (error) throw new Error(`entitlements write: ${error.message}`);
    },

    async freeScanUsed(userId) {
      const { count, error } = await supa.from("ai_usage")
        .select("id", { count: "exact", head: true })
        .eq("user_id", userId).eq("tier", "free").eq("status", "ok");
      if (error) throw new Error(`ai_usage free read: ${error.message}`);
      return (count ?? 0) > 0;
    },

    async capDay(userId) {
      const { data, error } = await supa.rpc("cap_day", { p_user: userId }).single();
      if (error) throw new Error(`cap_day: ${error.message}`);
      return data as CapDay;
    },

    async hasConsent(userId) {
      const { data, error } = await supa.from("profiles")
        .select("consent_health_at").eq("id", userId).maybeSingle();
      if (error) throw new Error(`profiles consent read: ${error.message}`);
      return !!(data as { consent_health_at: string | null } | null)?.consent_health_at;
    },

    async usageSince(userId, sinceIso, filter) {
      let q = supa.from("ai_usage")
        .select("created_at", { count: "exact" })
        .eq("user_id", userId).gte("created_at", sinceIso);
      if (filter.mode) q = q.eq("mode", filter.mode);
      if (filter.okOnly) q = q.eq("status", "ok");
      const { data, count, error } = await q.order("created_at", { ascending: true }).limit(1);
      if (error) throw new Error(`ai_usage window read: ${error.message}`);
      return { count: count ?? 0, oldest: (data?.[0] as { created_at?: string })?.created_at ?? null };
    },

    async insertUsage(row) {
      const { data, error } = await supa.from("ai_usage").insert(row).select("id").single();
      if (error) {
        if (error.code === "23505") return "free_scan_taken";
        throw new Error(`ai_usage insert: ${error.message}`);
      }
      return (data as { id: number }).id;
    },

    async insertDenial(row) {
      const { error } = await supa.from("ai_denials").insert(row);
      if (error) throw new Error(`ai_denials insert: ${error.message}`);
    },
  };
}
