// score.ts — pure scoring for the accuracy + cost eval (unit-tested in score_test.ts).
// Generic metrics here; "is this result right?" comes from score_app.ts (app-specific).
import type { AnalysisResult } from "../../supabase/functions/_shared/analysis.ts";
import { type Expected, scoreCase } from "./score_app.ts";

export interface Case {
  id: string;
  mode: "photo" | "text";
  image?: string | null;   // path under data/ (photo mode)
  text?: string | null;    // text mode
  expected: Expected;
}

export interface Sample {
  caseId: string;
  mode: "photo" | "text";
  outcome: "result" | "not_applicable" | "invalid" | "provider_error";
  result: AnalysisResult | null;
  latencyMs: number;
  costUsd: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
}

export interface ModelScore {
  model: string;
  n: number;
  accuracy: number | null;           // share of cases whose result passes scoreCase (failures count as misses)
  valid_json_rate: number | null;    // share of calls that returned a schema-valid result or not_applicable
  not_applicable_rate: number | null;
  provider_error_rate: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  cost_per_call_usd: number | null;  // mean fal usage.cost over calls that reported one
  cost_per_call_by_mode: Record<string, number | null>;
  total_cost_usd: number;
  metrics: Record<string, number>;   // app metrics (score_app.ts), averaged over successful results
}

export interface Bar {
  accuracy: number;        // e.g. 0.8
  validJson: number;       // e.g. 1.0
}

export const DEFAULT_BAR: Bar = { accuracy: 0.8, validJson: 1 };

const round = (x: number, d = 4) => Math.round(x * 10 ** d) / 10 ** d;

export function percentile(values: number[], p: number): number | null {
  if (values.length === 0) return null;
  const s = [...values].sort((a, b) => a - b);
  const idx = Math.min(s.length - 1, Math.max(0, Math.ceil((p / 100) * s.length) - 1));
  return s[idx];
}

function mean(xs: number[]): number | null {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}

export function scoreModel(model: string, samples: Sample[], cases: Map<string, Case>): ModelScore {
  const n = samples.length;
  let pass = 0;
  const metricSums: Record<string, number[]> = {};
  for (const s of samples) {
    if (s.outcome !== "result" || !s.result) continue;
    const c = cases.get(s.caseId);
    if (!c) continue;
    const sc = scoreCase(c.expected, s.result);
    if (sc.pass) pass++;
    for (const [k, v] of Object.entries(sc.metrics ?? {})) (metricSums[k] ??= []).push(v);
  }
  const costed = samples.filter((s) => s.costUsd !== null);
  const byMode: Record<string, number | null> = {};
  for (const mode of ["photo", "text"]) {
    const m = mean(costed.filter((s) => s.mode === mode).map((s) => s.costUsd!));
    byMode[mode] = m === null ? null : round(m, 6);
  }
  const rate = (f: (s: Sample) => boolean) => (n ? round(samples.filter(f).length / n) : null);
  const cost = mean(costed.map((s) => s.costUsd!));
  return {
    model,
    n,
    accuracy: n ? round(pass / n) : null,
    valid_json_rate: rate((s) => s.outcome === "result" || s.outcome === "not_applicable"),
    not_applicable_rate: rate((s) => s.outcome === "not_applicable"),
    provider_error_rate: rate((s) => s.outcome === "provider_error"),
    latency_p50_ms: percentile(samples.map((s) => s.latencyMs), 50),
    latency_p95_ms: percentile(samples.map((s) => s.latencyMs), 95),
    cost_per_call_usd: cost === null ? null : round(cost, 6),
    cost_per_call_by_mode: byMode,
    total_cost_usd: round(costed.reduce((a, s) => a + s.costUsd!, 0), 6),
    metrics: Object.fromEntries(Object.entries(metricSums).map(([k, v]) => [k, round(mean(v)!)])),
  };
}

export function passes(s: ModelScore, bar: Bar = DEFAULT_BAR): boolean {
  return (s.accuracy ?? 0) >= bar.accuracy && (s.valid_json_rate ?? 0) >= bar.validJson;
}

/** The cheapest passing model, and the next-cheapest passing one as fallback. */
export function choose(scores: ModelScore[], bar: Bar = DEFAULT_BAR): { primary: string | null; fallback: string | null } {
  const ok = scores.filter((s) => passes(s, bar)).sort((a, b) =>
    (a.cost_per_call_usd ?? Infinity) - (b.cost_per_call_usd ?? Infinity)
  );
  return { primary: ok[0]?.model ?? null, fallback: ok[1]?.model ?? null };
}
