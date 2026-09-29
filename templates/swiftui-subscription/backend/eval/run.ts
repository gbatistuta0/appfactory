// run.ts — accuracy + cost eval of candidate models on backend/eval/data (see backend/EVAL.md).
//
// Calls the model directly with the production prompt, schema and normalization (the same
// _shared/analysis.ts the edge function uses), so the only variable is the model. PAID: every
// case × model is one fal.ai call. --dry-run prints the estimate and exits (no key, no call);
// --max-cost is a hard budget that stops the run; --rescore recomputes scores from a saved run.
//
//   deno run -A backend/eval/run.ts --models=google/gemini-3.6-flash,… [--limit=N] [--concurrency=4]
//                                   [--max-cost=0.60] [--reasoning=minimal] [--cases=cases.json] [--dry-run]
//   deno run -A backend/eval/run.ts --rescore=results/<run>.json
//
// Output: results/<run>.json + .md. `scores[].cost_per_call_by_mode` is the measured cost per call
// (fal's usage.cost) that the factory's pricing_unit_economics tool feeds into store/pricing.md.
import { parseArgs } from "jsr:@std/cli@1/parse-args";
import { encodeBase64 } from "jsr:@std/encoding@1/base64";
import { parse as parseToml } from "jsr:@std/toml@1";
import {
  MAX_OUTPUT_TOKENS, OUTPUT_SCHEMA, parseOutput, SCHEMA_NAME, systemPrompt, userPrompt,
} from "../../supabase/functions/_shared/analysis.ts";
import { falClient, type LlmClient } from "../../supabase/functions/_shared/llm.ts";
import { languageName } from "../../supabase/functions/_shared/locale.ts";
import { type Case, choose, DEFAULT_BAR, passes, type Sample, scoreModel, type ModelScore } from "./score.ts";

const HERE = new URL("./", import.meta.url);

// OpenRouter list prices (USD per 1M tokens, input/output), checked 2026-09-24. Used for the
// dry-run estimate only; the measured cost is fal's usage.cost.
export const LIST_PRICE: Record<string, [number, number]> = {
  "google/gemini-3.8-flash": [0.75, 3.75],
  "google/gemini-3.6-flash": [0.75, 3.75],
  "google/gemini-3.5-flash-lite": [0.30, 2.50],
  "google/gemini-2.5-flash-lite": [0.10, 0.40],
};
// Token assumptions for the estimate (a 1024 px JPEG is ~1,300–1,800 input tokens on Gemini).
export const EST_TOKENS = { photo: [2000, 600], text: [900, 600] } as const;

export function estimateUsd(models: string[], cases: Case[]): number {
  return models.reduce((sum, m) => {
    const [pin, pout] = LIST_PRICE[m] ?? [1, 5];
    return sum + cases.reduce((a, c) => {
      const [tin, tout] = EST_TOKENS[c.mode];
      return a + (tin * pin + tout * pout) / 1e6;
    }, 0);
  }, 0);
}

/** fal key from FAL_KEY or the factory config; never printed. */
export async function falKey(): Promise<string> {
  const env = Deno.env.get("FAL_KEY");
  if (env) return env;
  const home = Deno.env.get("HOME") ?? "";
  const cfg = parseToml(await Deno.readTextFile(`${home}/.appfactory/config.toml`)) as Record<string, unknown>;
  const key = cfg.fal_key;
  if (typeof key !== "string" || !key) throw new Error("fal_key not found in ~/.appfactory/config.toml");
  return key;
}

async function pool<T>(items: T[], n: number, fn: (t: T) => Promise<void>) {
  const queue = [...items];
  await Promise.all(Array.from({ length: n }, async () => {
    for (let t = queue.shift(); t !== undefined; t = queue.shift()) await fn(t);
  }));
}

export async function runEval(opts: {
  llm: LlmClient;
  models: string[];
  cases: Case[];
  concurrency: number;
  maxCost: number;
  reasoning: string;
  locale?: string;
  loadImage: (path: string) => Promise<string>;
  onRaw?: (model: string, caseId: string, raw: unknown) => Promise<void>;
}) {
  let spent = 0;
  let stopped = false;
  const samples = new Map<string, Sample[]>(opts.models.map((m) => [m, []]));
  const jobs = opts.models.flatMap((model) => opts.cases.map((c) => ({ model, c })));
  const locale = opts.locale ?? "en";
  const system = systemPrompt(languageName(locale));

  await pool(jobs, opts.concurrency, async ({ model, c }) => {
    if (stopped) return;
    const user = userPrompt({ mode: c.mode, locale, note: null, text: c.text ?? null, options: {} });
    const image = c.mode === "photo" && c.image ? { mime: "image/jpeg", base64: await opts.loadImage(c.image) } : null;
    const result = await opts.llm({
      model, system, userText: user, image,
      schema: OUTPUT_SCHEMA as unknown as Record<string, unknown>, schemaName: SCHEMA_NAME,
      reasoning: opts.reasoning, maxTokens: MAX_OUTPUT_TOKENS, timeoutMs: 60_000,
    });
    const usage = result.usage;
    spent += usage?.costUsd ?? 0;
    if (spent >= opts.maxCost) stopped = true;
    const parsed = result.ok ? parseOutput(result.content) : null;
    samples.get(model)!.push({
      caseId: c.id,
      mode: c.mode,
      outcome: !result.ok ? "provider_error" : parsed!.kind === "result" ? "result"
        : parsed!.kind === "not_applicable" ? "not_applicable" : "invalid",
      result: parsed?.kind === "result" ? parsed.result : null,
      latencyMs: result.latencyMs,
      costUsd: usage?.costUsd ?? null,
      inputTokens: usage?.inputTokens ?? null,
      outputTokens: usage?.outputTokens ?? null,
    });
    await opts.onRaw?.(model, c.id, { result, parsed });
  });
  return { samples, spent, stopped };
}

export function markdown(runId: string, scores: ModelScore[], spent: number, setup = ""): string {
  const pct = (x: number | null) => (x === null ? "–" : `${(x * 100).toFixed(1)}%`);
  const usd = (x: number | null | undefined) => (x === null || x === undefined ? "–" : `$${x.toFixed(5)}`);
  const pick = choose(scores);
  return [
    `# Eval run ${runId}`,
    "",
    `${scores[0]?.n ?? 0} cases, production prompt and schema. ${setup} Total spent: $${spent.toFixed(4)}.`,
    "",
    "| Model | Pass | accuracy | valid JSON | not applicable | provider errors | p50 / p95 ms | $/call | $/photo | $/text |",
    "|---|---|---|---|---|---|---|---|---|---|",
    ...scores.map((s) =>
      `| ${s.model} | ${passes(s) ? "yes" : "no"} | ${pct(s.accuracy)} | ${pct(s.valid_json_rate)} | ${pct(s.not_applicable_rate)} | ${pct(s.provider_error_rate)} | ${s.latency_p50_ms ?? "–"} / ${s.latency_p95_ms ?? "–"} | ${usd(s.cost_per_call_usd)} | ${usd(s.cost_per_call_by_mode.photo)} | ${usd(s.cost_per_call_by_mode.text)} |`
    ),
    "",
    `Bar: accuracy ≥ ${DEFAULT_BAR.accuracy * 100}% (failed calls count as misses), valid JSON ${DEFAULT_BAR.validJson * 100}%.`,
    `Choice: primary ${pick.primary ?? "none passes"}, fallback ${pick.fallback ?? "–"}.`,
  ].join("\n") + "\n";
}

async function loadCases(name: string): Promise<Case[]> {
  const m = JSON.parse(await Deno.readTextFile(new URL(`data/${name}`, HERE))) as { cases: Case[] };
  return m.cases;
}

if (import.meta.main) {
  const args = parseArgs(Deno.args, {
    string: ["models", "reasoning", "rescore", "cases", "locale"],
    boolean: ["dry-run"],
    default: { limit: 0, concurrency: 4, "max-cost": 0.6, reasoning: "minimal", cases: "cases.json", locale: "en" },
  });
  if (args.rescore) {
    const saved = JSON.parse(await Deno.readTextFile(new URL(args.rescore, HERE)));
    const cases = new Map((await loadCases(saved.cases ?? "cases.json")).map((c) => [c.id, c]));
    saved.scores = Object.entries(saved.samples as Record<string, Sample[]>).map(([m, ss]) => scoreModel(m, ss, cases));
    await Deno.writeTextFile(new URL(args.rescore, HERE), JSON.stringify(saved, null, 2));
    const md = markdown(saved.runId, saved.scores, saved.spent, saved.setup ?? "");
    await Deno.writeTextFile(new URL(args.rescore.replace(/\.json$/, ".md"), HERE), md);
    console.log(md);
    Deno.exit(0);
  }
  const models = String(args.models ?? "").split(",").map((m) => m.trim()).filter(Boolean);
  if (models.length === 0) throw new Error("--models is required");
  const all = await loadCases(String(args.cases));
  const cases = Number(args.limit) > 0 ? all.slice(0, Number(args.limit)) : all;
  const maxCost = Number(args["max-cost"]);
  const estimate = estimateUsd(models, cases);
  console.log(`${models.length} models × ${cases.length} cases = ${models.length * cases.length} paid calls, ` +
    `estimate ≈ $${estimate.toFixed(3)}, budget $${maxCost}`);
  if (args["dry-run"]) Deno.exit(0);
  if (estimate > maxCost) console.log(`note: the estimate exceeds the budget; the run stops at $${maxCost}`);

  const runId = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const rawDir = new URL(`results/raw/${runId}/`, HERE);
  await Deno.mkdir(rawDir, { recursive: true });
  const setup = `Set: ${args.cases}, reasoning ${args.reasoning}, locale ${args.locale}.`;
  const { samples, spent, stopped } = await runEval({
    llm: falClient(await falKey()),
    models, cases, maxCost,
    concurrency: Number(args.concurrency),
    reasoning: String(args.reasoning),
    locale: String(args.locale),
    loadImage: async (p) => encodeBase64(await Deno.readFile(new URL(`data/${p}`, HERE))),
    onRaw: (model, id, raw) =>
      Deno.writeTextFile(new URL(`${model.replace(/\//g, "_")}__${id}.json`, rawDir), JSON.stringify(raw, null, 2)),
  });
  const byId = new Map(cases.map((c) => [c.id, c]));
  const scores = models.map((m) => scoreModel(m, samples.get(m)!, byId));
  const summary = {
    runId, spent, stopped, reasoning: args.reasoning, cases: args.cases, setup, scores,
    choice: choose(scores), samples: Object.fromEntries(samples),
  };
  await Deno.writeTextFile(new URL(`results/${runId}.json`, HERE), JSON.stringify(summary, null, 2));
  await Deno.writeTextFile(new URL(`results/${runId}.md`, HERE), markdown(runId, scores, spent, setup));
  console.log(markdown(runId, scores, spent, setup));
  if (stopped) console.log(`STOPPED: budget $${maxCost} reached`);
}
