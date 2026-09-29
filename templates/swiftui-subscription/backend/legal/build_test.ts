import { assertEquals } from "jsr:@std/assert@1";
import { markdownToText, placeholders, renderPage, stripComments, unrenderedBlocks } from "./build.ts";

Deno.test("placeholders are found only outside comments", () => {
  const md = "<!-- fill {{SUPPORT_EMAIL}} before publishing -->\nContact: {{ SUPPORT_EMAIL }} on {{PUBLISH_DATE}}";
  assertEquals(placeholders(stripComments(md)), ["{{ SUPPORT_EMAIL }}", "{{PUBLISH_DATE}}"]);
  assertEquals(placeholders(stripComments("<!-- {{X}} -->\nDone.")), []);
});

Deno.test("markdownToText: headings, paragraphs, lists, inline markup", () => {
  const md = [
    "# Title",
    "",
    "Line one",
    "continues **here** with a [link](https://x.y) and `code`.",
    "",
    "## Section",
    "",
    "- first item",
    "  wrapped",
    "- second *item*",
    "",
    "1. numbered",
    "",
    "---",
    "End.",
  ].join("\n");
  assertEquals(
    markdownToText(md),
    [
      "Title",
      "=====",
      "",
      "Line one continues here with a link (https://x.y) and code.",
      "",
      "Section",
      "-------",
      "",
      "• first item wrapped",
      "• second item",
      "",
      "1. numbered",
      "",
      "End.",
      "",
    ].join("\n"),
  );
});

Deno.test("markdownToText: a table becomes one block per row", () => {
  const md = "| Data | Why | Stored |\n|---|---|---|\n| Photos | Analysis | **No.** |\n| Log | History | Yes |\n\nAfter.";
  assertEquals(
    markdownToText(md),
    "• Photos\n  Why: Analysis\n  Stored: No.\n• Log\n  Why: History\n  Stored: Yes\n\nAfter.\n",
  );
});

Deno.test("renderPage keeps the document's own title, otherwise adds one", () => {
  assertEquals(renderPage("terms", "# Hue Terms\n\nHi.").split("\n")[0], "Hue Terms");
  assertEquals(renderPage("terms", "Hi.", "Hue").split("\n").slice(0, 3), ["Hue: Terms of Use", "=================", ""]);
  assertEquals(renderPage("support", "Hi.", "Hue").split("\n")[0], "Hue: Support");
});

Deno.test("unrendered conditional blocks are refused", () => {
  assertEquals(unrenderedBlocks("a\n<!-- if:consent.health -->\nHK\n<!-- endif -->\nb"), [
    "<!-- if:consent.health -->", "<!-- endif -->",
  ]);
  assertEquals(unrenderedBlocks("<!-- a normal editor note -->"), []);
});

import { verifyLegal } from "./verify.ts";

Deno.test("verifyLegal: language, email and placeholder checks per URL (fake fetch)", async () => {
  const fake = ((url: string | URL | Request) => {
    const u = new URL(String(url));
    const lang = u.searchParams.get("lang")!;
    if (u.pathname.endsWith("/terms") && lang === "de") return Promise.resolve(new Response("x", { status: 404 }));
    const served = lang === "fr" ? "en" : lang;
    const body = lang === "tr" ? "Contact {{SUPPORT_EMAIL}}" : "Contact help@example.com";
    return Promise.resolve(new Response(body, { headers: { "Content-Language": served } }));
  }) as typeof fetch;
  const checks = await verifyLegal("https://x.supabase.co/", "help@example.com", ["privacy", "terms"], fake);
  const bad = Object.fromEntries(checks.filter((c) => c.problems.length).map((c) => [c.url.split("/legal/")[1], c.problems]));
  assertEquals(bad["privacy?lang=fr"], ["served en"]);
  assertEquals(bad["privacy?lang=tr"], ["support email missing", "placeholder left"]);
  assertEquals(bad["terms?lang=de"], ["HTTP 404", "served null", "support email missing"]);
  assertEquals(checks[0].url, "https://x.supabase.co/functions/v1/legal/privacy?lang=en");
  assertEquals(checks[0].problems, []);
});
