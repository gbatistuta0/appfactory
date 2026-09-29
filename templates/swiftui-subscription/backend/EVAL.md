# __DISPLAY_NAME__ model accuracy and cost eval

Owner: backend. Purpose: pick the model by measured accuracy **and** measured cost, and re-check it
whenever the model, prompt, provider or prices change. The measured cost per call feeds the unit
economics in `store/pricing.md` (factory tool `pricing_unit_economics`).

## Dataset

- `backend/eval/data/cases.json`, built by `backend/eval/prepare.ts` from labelled local files
  (free, no API calls). Photos are converted to what the app sends (JPEG q80, long edge ≤ 1024, no
  metadata). Images are git-ignored; `cases.json` is committed.
- The template ships 3 neutral text cases. Replace them with at least 30 labelled cases that cover
  the app's real inputs (lighting, devices, edge cases, inputs the app must refuse), and record the
  source and licence of any public dataset here (e.g. Nutrition5k, CC BY 4.0).

## Method

- `backend/eval/run.ts` calls each candidate model directly with the **production** prompt, JSON
  schema and normalization (`supabase/functions/_shared/analysis.ts`), so the model is the only
  variable. No fallback inside the eval.
- Metrics (`backend/eval/score.ts`, unit-tested): accuracy (share of cases whose result passes the
  app's `score_app.ts` check; failed calls count as misses), valid JSON rate, not-applicable rate,
  provider-error rate, latency p50/p95, and **cost per call from fal's own `usage.cost`**, overall
  and per mode (photo/text).
- **Bar:** accuracy ≥ 80%, valid JSON 100% (edit `DEFAULT_BAR` if the lead sets another). Choose the
  cheapest passing model, with the next-cheapest passing model as fallback.

```bash
deno run --allow-read --allow-write --allow-run backend/eval/prepare.ts data/inbox cases.json    # free
deno run -A backend/eval/run.ts --models=google/gemini-3.6-flash,google/gemini-3.8-flash --dry-run  # estimate only
deno run -A backend/eval/run.ts --models=… --max-cost=0.60        # PAID: needs the lead's go
deno run -A backend/eval/run.ts --rescore=results/<run>.json      # free
```

The fal key is read from `FAL_KEY` or `~/.appfactory/config.toml` and is never printed.

## Results

No paid run yet. Paste the `results/<run>.md` table here with the date, the set and the reasoning
level, then the decision.

## Decision

- Primary: `spec.ai.model` (default `google/gemini-3.6-flash`, reasoning `minimal`). Fallback:
  `spec.ai.fallback_model` (default `google/gemini-3.8-flash`). Confirm or change after the first run.

## Cost per call (measured) and monthly exposure

Fill from the run: `$/photo` and `$/text` per call, then run `pricing_unit_economics` so
`store/pricing.md` §3 uses the measured numbers.
