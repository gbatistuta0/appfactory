// score_app.ts — APP-SPECIFIC EXTENSION POINT of the eval: is one model result right?
//
// The features stage replaces this with the app's own ground-truth comparison (a calorie app: kcal MAPE and
// ingredient identification against weighed Nutrition5k plates; Hue: palette/season match against
// labelled photos). Keep the signature: score.ts calls it once per successful result.
import type { AnalysisResult } from "../../supabase/functions/_shared/analysis.ts";

/** Ground truth for one case (cases.json `expected`), app-defined. */
export type Expected = Record<string, unknown>;

export interface CaseScore {
  pass: boolean;                     // counts toward the accuracy bar
  metrics?: Record<string, number>;  // extra numbers averaged per model (e.g. kcal_ape)
}

const words = (s: string) => s.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);

/**
 * Neutral example: the case passes when the result mentions at least one expected keyword in its
 * title, summary or tags (`expected.keywords: string[]`). `keyword_recall` is the share found.
 */
export function scoreCase(expected: Expected, result: AnalysisResult): CaseScore {
  const want = Array.isArray(expected.keywords) ? expected.keywords.map((k) => String(k).toLowerCase()) : [];
  if (want.length === 0) return { pass: true };
  const have = new Set([...words(result.title), ...words(result.summary), ...result.tags.flatMap(words)]);
  const found = want.filter((k) => words(k).every((w) => have.has(w)));
  return { pass: found.length > 0, metrics: { keyword_recall: found.length / want.length } };
}
