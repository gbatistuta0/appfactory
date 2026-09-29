// build.ts — turns the store's legal markdown into the text the `legal` edge function serves.
//
//   deno run --allow-read --allow-write backend/legal/build.ts
//
// Input:  store/privacy/privacy-policy.<lang>.md, terms.<lang>.md and support.<lang>.md for every
//         app language (app.gen.ts). `privacy-policy.md` / `terms.md` / `support.md` count as English.
// Output: supabase/functions/legal/content.gen.ts (commit it, then deploy `legal`).
//
// A document that still contains a {{PLACEHOLDER}} or an unrendered <!-- if:… --> block (run the
// factory's legal_render first) is never published: it is left out, the build lists it and exits
// non-zero. Missing translations are fine (the page falls back to English). Other HTML comments
// (editor notes) are stripped.
import { APP_NAME } from "../../supabase/functions/_shared/app.gen.ts";
import { SUPPORTED_LOCALES } from "../../supabase/functions/_shared/locale.ts";
import { LEGAL_DOCS, type LegalContent, type LegalDoc } from "../../supabase/functions/legal/handler.ts";

const ROOT = new URL("../../", import.meta.url);
const SOURCE_DIR = new URL("store/privacy/", ROOT);
const OUT = new URL("supabase/functions/legal/content.gen.ts", ROOT);
const FILE_BASE: Record<LegalDoc, string> = { privacy: "privacy-policy", terms: "terms", support: "support" };
const TITLE: Record<LegalDoc, string> = { privacy: "Privacy Policy", terms: "Terms of Use", support: "Support" };

export function stripComments(md: string): string {
  return md.replace(/<!--[\s\S]*?-->/g, "");
}

export function placeholders(md: string): string[] {
  return [...new Set(md.match(/\{\{\s*[A-Za-z0-9_]+\s*\}\}/g) ?? [])];
}

/** Conditional blocks left in the source (legal_render resolves them from app.spec.json). */
export function unrenderedBlocks(md: string): string[] {
  return [...new Set(md.match(/<!--\s*(?:if:[\w.]+|endif)\s*-->/g) ?? [])];
}

function inline(s: string): string {
  return s
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, t, u) => (t === u ? u : `${t} (${u})`))
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1$2")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const cells = (row: string) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => inline(c));

/**
 * Markdown → readable plain text for a browser's text/plain view: paragraphs become single lines
 * (the browser wraps them), headings are underlined, list items get "•", and each table row
 * becomes a small block ("• first cell" then "  Header: value" lines).
 */
export function markdownToText(md: string): string {
  const lines = stripComments(md).replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) out.push(inline(para.join(" ")), "");
    para = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const t = line.trim();
    if (t === "") {
      flush();
      continue;
    }
    const h = t.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      flush();
      const title = inline(h[2]);
      out.push(title, (h[1].length === 1 ? "=" : "-").repeat(Math.min(title.length, 60)), "");
      continue;
    }
    if (t.startsWith("|") && lines[i + 1]?.trim().match(/^\|?\s*:?-{3,}/)) {
      flush();
      const header = cells(t);
      i += 2;
      for (; i < lines.length && lines[i].trim().startsWith("|"); i++) {
        const row = cells(lines[i]);
        out.push(`• ${row[0]}`);
        for (let c = 1; c < row.length; c++) if (row[c]) out.push(`  ${header[c] ? header[c] + ": " : ""}${row[c]}`);
      }
      i--;
      out.push("");
      continue;
    }
    const li = t.match(/^([-*+]|\d+\.)\s+(.*)$/);
    if (li) {
      flush();
      // Continuation lines of a list item are indented.
      let item = li[2];
      while (i + 1 < lines.length && /^\s{2,}\S/.test(lines[i + 1]) && !/^\s*([-*+]|\d+\.)\s/.test(lines[i + 1])) {
        item += " " + lines[++i].trim();
      }
      out.push(`${/\d/.test(li[1]) ? li[1] : "•"} ${inline(item)}`);
      if (!/^\s*([-*+]|\d+\.)\s/.test(lines[i + 1] ?? "")) out.push("");
      continue;
    }
    if (/^(-{3,}|\*{3,})$/.test(t)) {
      flush();
      continue;
    }
    para.push(t);
  }
  flush();
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n";
}

/** The document's own "# Title" is used when present; otherwise a standard title is added. */
export function renderPage(doc: LegalDoc, md: string, appName = APP_NAME): string {
  if (/^#\s/.test(stripComments(md).trimStart())) return markdownToText(md);
  const title = `${appName}: ${TITLE[doc]}`;
  return `${title}\n${"=".repeat(title.length)}\n\n${markdownToText(md)}`;
}

async function readIfExists(url: URL): Promise<string | null> {
  try {
    return await Deno.readTextFile(url);
  } catch (e) {
    if (e instanceof Deno.errors.NotFound) return null;
    throw e;
  }
}

if (import.meta.main) {
  const content: LegalContent = { privacy: {}, terms: {}, support: {} };
  const refused: string[] = [];
  const published: string[] = [];
  for (const doc of LEGAL_DOCS) {
    for (const lang of SUPPORTED_LOCALES) {
      const names = [`${FILE_BASE[doc]}.${lang}.md`, ...(lang === "en" ? [`${FILE_BASE[doc]}.md`] : [])];
      for (const name of names) {
        const md = await readIfExists(new URL(name, SOURCE_DIR));
        if (md === null) continue;
        const open = [...unrenderedBlocks(md), ...placeholders(stripComments(md))];
        if (open.length) {
          refused.push(`store/privacy/${name}: ${open.join(", ")}`);
        } else {
          content[doc][lang] = renderPage(doc, md);
          published.push(`${doc}/${lang} ← store/privacy/${name}`);
        }
        break;
      }
    }
  }
  const header = `// GENERATED by backend/legal/build.ts from store/privacy/*.md. Do not edit by hand.\n` +
    `import type { LegalContent } from "./handler.ts";\n\n`;
  await Deno.writeTextFile(OUT, `${header}export const LEGAL: LegalContent = ${JSON.stringify(content, null, 2)};\n`);
  console.log(published.length ? `published:\n  ${published.join("\n  ")}` : "published: nothing");
  if (refused.length) {
    console.error(`NOT published (unfilled placeholders or unrendered blocks):\n  ${refused.join("\n  ")}`);
    Deno.exit(1);
  }
}
