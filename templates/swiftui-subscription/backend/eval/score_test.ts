// score_test.ts — scoring, cost aggregation, budget stop, dry-run estimate and case building.
// No network and no paid calls: the model is a fake LlmClient.
import { assert, assertEquals } from "jsr:@std/assert@1";
import type { LlmClient, LlmRequest } from "../../supabase/functions/_shared/llm.ts";
import { buildCases, caseId } from "./prepare.ts";
import { estimateUsd, markdown, runEval } from "./run.ts";
import { type Case, choose, passes, percentile, type Sample, scoreModel } from "./score.ts";
import { scoreCase } from "./score_app.ts";

const CASES: Case[] = [
  { id: "a", mode: "photo", image: "images/a.jpg", expected: { keywords: ["sunset"] } },
  { id: "b", mode: "text", text: "red door", expected: { keywords: ["door"] } },
  { id: "c", mode: "text", text: "noise", expected: {} },
];
const BY_ID = new Map(CASES.map((c) => [c.id, c]));
const result = (title: string, tags: string[] = []) => ({ title, summary: "s", tags, confidence: 0.9 });

function sample(caseId: string, mode: "photo" | "text", outcome: Sample["outcome"], cost: number | null, latency = 100, r = result("x")): Sample {
  return { caseId, mode, outcome, result: outcome === "result" ? r : null, latencyMs: latency, costUsd: cost, inputTokens: 10, outputTokens: 5 };
}

Deno.test("scoreCase (neutral example): keyword recall", () => {
  assertEquals(scoreCase({ keywords: ["sunset", "sea"] }, result("Sunset", ["calm sea"])), { pass: true, metrics: { keyword_recall: 1 } });
  assertEquals(scoreCase({ keywords: ["door"] }, result("A wall")).pass, false);
  assertEquals(scoreCase({}, result("x")), { pass: true });
});

Deno.test("scoreModel: accuracy counts failures as misses; cost per call by mode from usage.cost", () => {
  const s = scoreModel("m", [
    sample("a", "photo", "result", 0.002, 100, result("Sunset")),
    sample("b", "text", "result", 0.001, 300, result("A wall")),
    sample("c", "text", "provider_error", null, 900),
  ], BY_ID);
  assertEquals(s.accuracy, 0.3333);
  assertEquals(s.valid_json_rate, 0.6667);
  assertEquals(s.provider_error_rate, 0.3333);
  assertEquals(s.cost_per_call_usd, 0.0015);
  assertEquals(s.cost_per_call_by_mode, { photo: 0.002, text: 0.001 });
  assertEquals(s.total_cost_usd, 0.003);
  assertEquals([s.latency_p50_ms, s.latency_p95_ms], [300, 900]);
  assertEquals(s.metrics, { keyword_recall: 0.5 });
  assertEquals(percentile([], 50), null);
});

Deno.test("passes/choose: cheapest passing model is primary, next cheapest is fallback", () => {
  const mk = (model: string, accuracy: number, valid: number, cost: number) => ({
    model, n: 10, accuracy, valid_json_rate: valid, not_applicable_rate: 0, provider_error_rate: 0,
    latency_p50_ms: 1, latency_p95_ms: 1, cost_per_call_usd: cost, cost_per_call_by_mode: {}, total_cost_usd: 0, metrics: {},
  });
  const scores = [mk("big", 0.9, 1, 0.003), mk("cheap", 0.85, 1, 0.001), mk("broken", 0.95, 0.9, 0.0005), mk("mid", 0.8, 1, 0.002)];
  assert(!passes(scores[2]));
  assertEquals(choose(scores), { primary: "cheap", fallback: "mid" });
  assertEquals(choose([mk("x", 0.1, 1, 1)]), { primary: null, fallback: null });
  assert(markdown("r1", scores, 0.01).includes("Choice: primary cheap, fallback mid"));
});

Deno.test("estimateUsd uses list prices and per-mode token assumptions", () => {
  const est = estimateUsd(["google/gemini-3.6-flash"], CASES);
  // photo: (2000×0.75 + 600×3.75)/1e6 = 0.00375; text: (900×0.75 + 600×3.75)/1e6 = 0.002925 (×2)
  assertEquals(Math.round(est * 1e6), 3750 + 2 * 2925);
});

function fakeLlm(cost: number): LlmClient & { calls: LlmRequest[] } {
  const calls: LlmRequest[] = [];
  const fn = ((req: LlmRequest) => {
    calls.push(req);
    return Promise.resolve({
      ok: true, model: req.model, finishReason: "stop", latencyMs: 50,
      content: JSON.stringify({ is_applicable: true, title: "Sunset door", summary: "s", tags: [], confidence: 0.5 }),
      usage: { inputTokens: 100, outputTokens: 20, thinkingTokens: 0, costUsd: cost },
    });
  }) as LlmClient & { calls: LlmRequest[] };
  fn.calls = calls;
  return fn;
}

Deno.test("runEval: production prompt/schema, image only for photo cases, budget stops the run", async () => {
  const llm = fakeLlm(0.01);
  const { samples, spent, stopped } = await runEval({
    llm, models: ["m1", "m2"], cases: CASES, concurrency: 1, maxCost: 0.025, reasoning: "minimal",
    loadImage: () => Promise.resolve("AAAA"),
  });
  assert(stopped);
  assertEquals(llm.calls.length, 3);                 // 0.01 × 3 ≥ 0.025 → stop
  assertEquals(Math.round(spent * 1000), 30);
  assertEquals(llm.calls[0].image, { mime: "image/jpeg", base64: "AAAA" });
  assertEquals(llm.calls[1].image, null);
  assertEquals(llm.calls[0].schemaName, "analysis");
  assertEquals(samples.get("m1")!.length, 3);
  assertEquals(samples.get("m2")!.length, 0);
});

Deno.test("prepare: photo cases with sidecar truth, text cases, duplicate ids refused", async () => {
  const dir = await Deno.makeTempDir();
  const inbox = new URL(`file://${dir}/inbox/`);
  const images = new URL(`file://${dir}/images/`);
  await Deno.mkdir(inbox, { recursive: true });
  await Deno.mkdir(images, { recursive: true });
  await Deno.writeTextFile(new URL("Red Door.JPG", inbox), "x");
  await Deno.writeTextFile(new URL("Red Door.json", inbox), '{"keywords":["door"]}');
  await Deno.writeTextFile(new URL("text.json", inbox), '[{"id":"t1","text":"hello","expected":{"keywords":["x"]}}]');
  const converted: string[] = [];
  const cases = await buildCases(inbox, (_s, d) => (converted.push(d), Promise.resolve()), images);
  assertEquals(cases, [
    { id: "red-door", mode: "photo", image: "images/red-door.jpg", text: null, expected: { keywords: ["door"] } },
    { id: "t1", mode: "text", image: null, text: "hello", expected: { keywords: ["x"] } },
  ]);
  assert(converted[0].endsWith("/images/red-door.jpg"));
  assertEquals(caseId("A b.png"), "a-b");
  await Deno.writeTextFile(new URL("text.json", inbox), '[{"id":"red-door","text":"dup"}]');
  let threw = false;
  try {
    await buildCases(inbox, () => Promise.resolve(), images);
  } catch {
    threw = true;
  }
  assert(threw);
  await Deno.remove(dir, { recursive: true });
});
