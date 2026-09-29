// llm.ts — LLM client (text + optional image): fal.ai's OpenAI-compatible passthrough to OpenRouter.
//
// Why this endpoint: it is the fal route that forwards response_format (strict JSON schema) and
// reasoning controls, and it reports the real charge in usage.cost.
// Privacy on every call:
//   X-Fal-Store-IO: 0             → fal does not keep the request/response JSON (default: 30 days)
//   provider.data_collection deny → OpenRouter only routes to providers that do not train on inputs

export const FAL_CHAT_URL = "https://fal.run/openrouter/router/openai/v1/chat/completions";

export interface LlmRequest {
  model: string;
  system: string;
  userText: string;
  image: { mime: string; base64: string } | null;
  schema: Record<string, unknown>;
  schemaName?: string;   // response_format json_schema name (default "result")
  reasoning: string;     // none | minimal | low | medium | high
  maxTokens: number;
  timeoutMs: number;
}

export interface LlmUsage {
  inputTokens: number | null;
  outputTokens: number | null;
  thinkingTokens: number | null;
  costUsd: number | null;
}

export type LlmResult =
  | { ok: true; model: string; content: string; finishReason: string | null; usage: LlmUsage; latencyMs: number }
  | {
    ok: false;
    model: string;
    kind: "http" | "timeout" | "network" | "refused" | "truncated";
    status: number | null;
    message: string;
    usage: LlmUsage | null;
    latencyMs: number;
  };

export type LlmClient = (req: LlmRequest) => Promise<LlmResult>;

/**
 * Maps the configured reasoning level to what each model family accepts via OpenRouter.
 * Gemini 3.7/3.8 Flash reject "minimal" (lowest is "low"); Gemini 2.5 uses a budget, so
 * "minimal"/"none" there means reasoning off.
 */
export function reasoningFor(model: string, level: string): Record<string, unknown> {
  const m = model.toLowerCase();
  if (level === "none") return { enabled: false, exclude: true };
  if (/gemini-2\.5/.test(m) && level === "minimal") return { enabled: false, exclude: true };
  if (/gemini-3\.[78]-flash(?!-lite)/.test(m) && level === "minimal") return { effort: "low", exclude: true };
  return { effort: level, exclude: true };
}

export function buildChatBody(req: LlmRequest): Record<string, unknown> {
  const content: Array<Record<string, unknown>> = [{ type: "text", text: req.userText }];
  if (req.image) {
    content.push({
      type: "image_url",
      image_url: { url: `data:${req.image.mime};base64,${req.image.base64}` },
    });
  }
  return {
    model: req.model,
    messages: [
      { role: "system", content: req.system },
      { role: "user", content },
    ],
    response_format: {
      type: "json_schema",
      json_schema: { name: req.schemaName ?? "result", strict: true, schema: req.schema },
    },
    reasoning: reasoningFor(req.model, req.reasoning),
    max_tokens: req.maxTokens,
    provider: { data_collection: "deny" },
    stream: false,
  };
}

function usageFrom(u: unknown): LlmUsage | null {
  if (!u || typeof u !== "object") return null;
  const o = u as Record<string, unknown>;
  const n = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const details = (o.completion_tokens_details ?? {}) as Record<string, unknown>;
  return {
    inputTokens: n(o.prompt_tokens),
    outputTokens: n(o.completion_tokens),
    thinkingTokens: n(details.reasoning_tokens),
    costUsd: n(o.cost),
  };
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const o = body as Record<string, unknown>;
    const err = o.error as Record<string, unknown> | string | undefined;
    if (typeof err === "string") return err;
    if (err && typeof err.message === "string") return err.message;
    if (typeof o.detail === "string") return o.detail;
    if (o.detail) return JSON.stringify(o.detail).slice(0, 300);
  }
  return fallback;
}

export function falClient(apiKey: string, fetchImpl: typeof fetch = fetch): LlmClient {
  return async (req) => {
    const started = Date.now();
    const elapsed = () => Date.now() - started;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), req.timeoutMs);
    let res: Response;
    try {
      res = await fetchImpl(FAL_CHAT_URL, {
        method: "POST",
        headers: {
          "Authorization": `Key ${apiKey}`,
          "Content-Type": "application/json",
          "X-Fal-Store-IO": "0",
        },
        body: JSON.stringify(buildChatBody(req)),
        signal: controller.signal,
      });
    } catch (e) {
      clearTimeout(timer);
      const aborted = (e as Error).name === "AbortError";
      return {
        ok: false, model: req.model, kind: aborted ? "timeout" : "network", status: null,
        message: aborted ? `timeout after ${req.timeoutMs} ms` : String(e), usage: null, latencyMs: elapsed(),
      };
    }

    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    } finally {
      clearTimeout(timer);
    }
    if (!res.ok) {
      return {
        ok: false, model: req.model, kind: "http", status: res.status,
        message: errorMessage(body, `HTTP ${res.status}`), usage: usageFrom((body as any)?.usage),
        latencyMs: elapsed(),
      };
    }

    const o = (body ?? {}) as Record<string, any>;
    const usage = usageFrom(o.usage) ?? { inputTokens: null, outputTokens: null, thinkingTokens: null, costUsd: null };
    if (o.error) {
      return {
        ok: false, model: req.model, kind: "http", status: Number(o.error.code) || 502,
        message: errorMessage(o, "provider error"), usage, latencyMs: elapsed(),
      };
    }
    const choice = Array.isArray(o.choices) ? o.choices[0] : null;
    const finishReason: string | null = choice?.finish_reason ?? choice?.native_finish_reason ?? null;
    const content = choice?.message?.content;
    if (finishReason === "content_filter") {
      return { ok: false, model: req.model, kind: "refused", status: 200, message: "content_filter", usage, latencyMs: elapsed() };
    }
    if (finishReason === "error") {
      // OpenRouter reports a provider failure mid-generation this way; content is partial.
      return { ok: false, model: req.model, kind: "http", status: 502, message: "provider error mid-generation", usage, latencyMs: elapsed() };
    }
    if (finishReason === "length") {
      return { ok: false, model: req.model, kind: "truncated", status: 200, message: "max_tokens reached", usage, latencyMs: elapsed() };
    }
    if (typeof content !== "string" || content.trim() === "") {
      return { ok: false, model: req.model, kind: "http", status: 200, message: "empty content", usage, latencyMs: elapsed() };
    }
    return { ok: true, model: req.model, content, finishReason, usage, latencyMs: elapsed() };
  };
}
