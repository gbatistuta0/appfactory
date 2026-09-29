// legal — public Privacy Policy, Terms of Use and Support pages (no JWT; linked from the app, the
// paywall and App Store Connect).
//
//   GET /functions/v1/legal/privacy[?lang=tr]
//   GET /functions/v1/legal/terms[?lang=de]
//   GET /functions/v1/legal/support[?lang=fr]
//
// Plain text on purpose: the hosted Supabase gateway serves every edge-function (and Storage)
// response on *.supabase.co as text/plain with a sandbox CSP, so HTML would show as raw source.
// The text comes from store/privacy/*.md via backend/legal/build.ts (content.gen.ts).
// Language: ?lang=, else the best Accept-Language match, else the fallback language; a missing
// translation falls back to the fallback language (English).
import { APP_NAME } from "../_shared/app.gen.ts";
import { type AppLocale, matchLocale, SUPPORTED_LOCALES } from "../_shared/locale.ts";

export type LegalDoc = "privacy" | "terms" | "support";
export type LegalContent = Record<LegalDoc, Partial<Record<AppLocale, string>>>;
export const LEGAL_DOCS: LegalDoc[] = ["privacy", "terms", "support"];

const TITLES: Record<LegalDoc, string> = { privacy: "Privacy Policy", terms: "Terms of Use", support: "Support" };

function text(body: string, status = 200, extra: Record<string, string> = {}): Response {
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/plain; charset=utf-8", ...extra },
  });
}

/** Languages from Accept-Language, best first ("tr-TR,tr;q=0.9,en;q=0.5" → tr, en). */
export function acceptedLocales(header: string | null): AppLocale[] {
  if (!header) return [];
  return header.split(",")
    .map((part, i) => {
      const [tag, ...params] = part.trim().split(";");
      const q = params.map((p) => p.trim()).find((p) => p.startsWith("q="));
      return { tag, q: q ? Number(q.slice(2)) || 0 : 1, i };
    })
    .filter((x) => x.q > 0)
    .sort((a, b) => b.q - a.q || a.i - b.i)
    .map((x) => matchLocale(x.tag))
    .filter((l): l is AppLocale => l !== null);
}

export function pickLocale(
  available: Partial<Record<AppLocale, string>>,
  query: string | null,
  acceptLanguage: string | null,
): AppLocale | null {
  const wanted = [matchLocale(query), ...acceptedLocales(acceptLanguage), SUPPORTED_LOCALES[0] as AppLocale]
    .filter((l): l is AppLocale => l !== null);
  return wanted.find((l) => available[l] !== undefined) ?? null;
}

export function createHandler(content: LegalContent, baseUrl: string, appName = APP_NAME): (req: Request) => Response {
  return (req) => {
    if (req.method !== "GET" && req.method !== "HEAD") return text("Method not allowed\n", 405);
    const url = new URL(req.url);
    const doc = url.pathname.split("/").filter(Boolean).pop() as LegalDoc | undefined;
    if (!doc || !LEGAL_DOCS.includes(doc)) {
      return text(`Not found. Available:\n${LEGAL_DOCS.map((d) => `${baseUrl}/${d}`).join("\n")}\n`, 404);
    }
    const available = content[doc] ?? {};
    const locale = pickLocale(available, url.searchParams.get("lang"), req.headers.get("Accept-Language"));
    if (!locale) {
      return text(`${appName} ${TITLES[doc]}\n\nThis page has not been published yet.\n`, 404, { "Cache-Control": "no-store" });
    }
    const others = SUPPORTED_LOCALES.filter((l) => l !== locale && available[l] !== undefined)
      .map((l) => `${l}: ${baseUrl}/${doc}?lang=${l}`);
    const body = available[locale]!.trimEnd() + "\n" +
      (others.length ? `\n----\n${others.join("\n")}\n` : "");
    return text(req.method === "HEAD" ? "" : body, 200, {
      "Content-Language": locale,
      "Cache-Control": "public, max-age=3600",
      "Vary": "Accept-Language",
    });
  };
}
