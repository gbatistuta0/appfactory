import { assertEquals, assertStringIncludes } from "jsr:@std/assert@1";
import { acceptedLocales, createHandler, type LegalContent, pickLocale } from "../functions/legal/handler.ts";

const BASE = "https://x.supabase.co/functions/v1/legal";
const CONTENT: LegalContent = {
  privacy: { en: "Privacy EN\n", tr: "Gizlilik TR\n", de: "Datenschutz DE\n" },
  terms: {},
  support: { en: "Support EN\n" },
};

Deno.test("acceptedLocales orders by q and drops unsupported languages", () => {
  assertEquals(acceptedLocales("it-IT,tr;q=0.8,de;q=0.9,en;q=0"), ["de", "tr"]);
  assertEquals(acceptedLocales("pt-PT, es-MX;q=0.5"), ["pt-BR", "es"]);
  assertEquals(acceptedLocales(null), []);
});

Deno.test("pickLocale: ?lang, then Accept-Language, then English; skips missing translations", () => {
  const av = CONTENT.privacy;
  assertEquals(pickLocale(av, "tr", "de"), "tr");
  assertEquals(pickLocale(av, "fr", "it, de;q=0.5"), "de");   // no French yet
  assertEquals(pickLocale(av, null, "es-ES"), "en");
  assertEquals(pickLocale({}, "tr", "tr"), null);
});

Deno.test("legal handler: serves plain text with language headers and links", async () => {
  const h = createHandler(CONTENT, BASE);
  const res = h(new Request(`${BASE}/privacy`, { headers: { "Accept-Language": "tr-TR,tr;q=0.9" } }));
  assertEquals(res.status, 200);
  assertEquals(res.headers.get("Content-Type"), "text/plain; charset=utf-8");
  assertEquals(res.headers.get("Content-Language"), "tr");
  assertEquals(res.headers.get("Vary"), "Accept-Language");
  const body = await res.text();
  assertStringIncludes(body, "Gizlilik TR");
  assertStringIncludes(body, `en: ${BASE}/privacy?lang=en`);
  assertStringIncludes(body, `de: ${BASE}/privacy?lang=de`);

  const q = h(new Request(`${BASE}/privacy?lang=de`, { headers: { "Accept-Language": "tr" } }));
  assertEquals(q.headers.get("Content-Language"), "de");
  await q.body?.cancel();
});

Deno.test("legal handler: unpublished doc, unknown path, method", async () => {
  const h = createHandler(CONTENT, BASE);
  const terms = h(new Request(`${BASE}/terms`));
  assertEquals(terms.status, 404);
  const termsText = await terms.text();
  assertStringIncludes(termsText, "not been published yet");
  assertStringIncludes(termsText, "Terms of Use");
  const other = h(new Request(`${BASE}/cookies`));
  assertEquals(other.status, 404);
  const listing = await other.text();
  assertStringIncludes(listing, `${BASE}/privacy`);
  assertStringIncludes(listing, `${BASE}/support`);
  const support = h(new Request(`${BASE}/support?lang=tr`));
  assertEquals([support.status, support.headers.get("Content-Language")], [200, "en"]);   // falls back to en
  await support.body?.cancel();
  assertEquals(h(new Request(`${BASE}/privacy`, { method: "POST" })).status, 405);
  const head = h(new Request(`${BASE}/privacy`, { method: "HEAD" }));
  assertEquals([head.status, await head.text()], [200, ""]);
});
