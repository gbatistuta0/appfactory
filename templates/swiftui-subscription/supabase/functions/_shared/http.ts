// http.ts — response helpers and request-input validation shared by the edge functions.

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

export function bearer(req: Request): string | null {
  const h = req.headers.get("Authorization") ?? "";
  const m = h.match(/^Bearer\s+(.+)$/i);
  return m ? m[1].trim() : null;
}

export type ImageCheck =
  | { ok: true; mime: "image/jpeg" | "image/png" | "image/webp"; base64: string; bytes: number }
  | { ok: false; status: number; error: string; message: string };

const B64 = /^[A-Za-z0-9+/]+={0,2}$/;

/**
 * Validates a base64 image without decoding all of it: size from the base64 length, type from
 * the magic bytes (the client's declared mime type is ignored). Accepts an optional data: prefix.
 */
export function checkImage(data: unknown, maxBytes: number): ImageCheck {
  if (typeof data !== "string" || data.length === 0) {
    return { ok: false, status: 400, error: "invalid_request", message: "image.data must be a base64 string" };
  }
  const base64 = data.replace(/^data:[^;,]*;base64,/, "").replace(/\s+/g, "");
  if (base64.length % 4 !== 0 || !B64.test(base64)) {
    return { ok: false, status: 400, error: "invalid_request", message: "image.data is not valid base64" };
  }
  const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
  const bytes = (base64.length / 4) * 3 - padding;
  if (bytes > maxBytes) {
    return { ok: false, status: 413, error: "image_too_large", message: `image must be at most ${maxBytes} bytes` };
  }
  if (bytes < 16) {
    return { ok: false, status: 400, error: "invalid_request", message: "image is empty" };
  }
  const head = Uint8Array.from(atob(base64.slice(0, 16)), (c) => c.charCodeAt(0));
  const ascii = (from: number, to: number) => String.fromCharCode(...head.slice(from, to));
  if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) return { ok: true, mime: "image/jpeg", base64, bytes };
  if (head[0] === 0x89 && ascii(1, 4) === "PNG") return { ok: true, mime: "image/png", base64, bytes };
  if (ascii(0, 4) === "RIFF" && ascii(8, 12) === "WEBP") return { ok: true, mime: "image/webp", base64, bytes };
  return { ok: false, status: 415, error: "unsupported_image", message: "send a JPEG, PNG or WebP image" };
}
