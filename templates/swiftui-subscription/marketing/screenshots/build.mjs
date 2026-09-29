// App Store screenshot compositor (generalized, with script rules from a
// 36-locale store set). Reads the raw simulator captures raw/<locale>/NN_*.png, adds the brand
// gradient and the caption, and writes Apple-canonical PNGs to branded/<locale>/NN_*.png.
//
// Captions come from copy/<locale>.json ([{headline, subhead}, ...]), falling back to copy/en-US.json.
// Usage: node build.mjs            (FIT_STRICT=1 fails the run when a caption does not fit)
//
// Every script renders like the app does:
// - per-script system font stacks (the brand fonts rarely cover Arabic, Hebrew, Devanagari, Thai or CJK);
//   Arabic has no "Geeza Pro" fallback: at heavy weights its ٬ thousands separator draws with a gap;
// - ar/he/fa/ur are right-to-left (direction + bidi embedding);
// - lines break by word segments (Intl.Segmenter), so Japanese, Chinese and Thai, which have no
//   spaces, wrap too; CJK characters count double in the line width;
// - taller line height for scripts with tall marks, and no negative tracking outside Latin.
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const cfg = JSON.parse(await fs.readFile(path.join(ROOT, "config.json"), "utf-8"));
const W = cfg.canvas?.w ?? 1320;
const H = cfg.canvas?.h ?? 2868;
const MAX_HEADLINE_LINES = cfg.maxHeadlineLines ?? 3;

const LATIN = '-apple-system, "SF Pro Display", "Helvetica Neue", Helvetica, Arial, sans-serif';
const SYSTEM = 'system-ui, -apple-system, "Helvetica Neue", sans-serif';
const SCRIPT_FONTS = {
  ar: "system-ui, -apple-system, sans-serif",
  fa: "system-ui, -apple-system, sans-serif",
  ur: "system-ui, -apple-system, sans-serif",
  he: 'system-ui, -apple-system, "Arial Hebrew", sans-serif',
  hi: '"Kohinoor Devanagari", system-ui, sans-serif',
  th: "Thonburi, system-ui, sans-serif",
  ja: '"Hiragino Sans", "Hiragino Kaku Gothic ProN", sans-serif',
  ko: '"Apple SD Gothic Neo", system-ui, sans-serif',
  "zh-Hans": '"PingFang SC", "Hiragino Sans GB", sans-serif',
  "zh-Hant": '"PingFang TC", "Heiti TC", sans-serif',
  ru: SYSTEM, uk: SYSTEM, el: SYSTEM, vi: SYSTEM,
};
const RTL = new Set(["ar", "he", "fa", "ur"]);
const TALL = { ar: 1.3, hi: 1.3, th: 1.3, vi: 1.2, ja: 1.25, ko: 1.25, "zh-Hans": 1.25, "zh-Hant": 1.25 };

/** ASC locale → the language the rules above are keyed by ("de-DE" → "de", "zh-Hant" stays). */
export function lang(locale) {
  if (locale.startsWith("zh-")) return locale.includes("Hant") || /TW|HK|MO/.test(locale) ? "zh-Hant" : "zh-Hans";
  return locale.split("-")[0];
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function loadCopy(locale) {
  for (const loc of [locale, "en-US"]) {
    try {
      return JSON.parse(await fs.readFile(path.join(ROOT, "copy", `${loc}.json`), "utf-8"));
    } catch { /* try the fallback */ }
  }
  return [];
}

function backgroundSVG() {
  return Buffer.from(`<svg width="${W}" height="${H}">
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${cfg.brandColorTop}"/>
      <stop offset="100%" stop-color="${cfg.brandColorBottom}"/>
    </linearGradient></defs>
    <rect width="${W}" height="${H}" fill="url(#g)"/>
  </svg>`);
}

/** Width in "Latin character" units: East Asian wide characters count 2, combining marks 0. */
export function displayWidth(text) {
  let w = 0;
  for (const ch of text) {
    if (/\p{Mn}/u.test(ch)) continue;
    const c = ch.codePointAt(0);
    const wide = (c >= 0x1100 && c <= 0x115f) || (c >= 0x2e80 && c <= 0xa4cf) || (c >= 0xac00 && c <= 0xd7a3) ||
      (c >= 0xf900 && c <= 0xfaff) || (c >= 0xfe30 && c <= 0xfe4f) || (c >= 0xff00 && c <= 0xff60) ||
      (c >= 0xffe0 && c <= 0xffe6);
    w += wide ? 2 : 1;
  }
  return w;
}

/** Break into lines of at most `maxUnits` display units, at word segments (works without spaces). */
export function wrapText(text, maxUnits, locale = "en") {
  const segs = [...new Intl.Segmenter(lang(locale), { granularity: "word" }).segment(String(text ?? "").trim())]
    .map((s) => s.segment);
  const lines = [];
  let cur = "";
  for (const seg of segs) {
    if (cur.trim() && displayWidth(cur + seg) > maxUnits && seg.trim()) {
      lines.push(cur.trim());
      cur = seg;
    } else {
      cur += seg;
    }
  }
  if (cur.trim()) lines.push(cur.trim());
  return lines.length ? lines : [""];
}

// Big, readable headline + subhead. Returns the real height so the capture sits below it (no overlap).
function textBlock(headline, subhead, locale) {
  const l = lang(locale);
  const hc = cfg.headlineColor ?? "#FFFFFF";
  const font = SCRIPT_FONTS[l] ?? LATIN;
  const tall = TALL[l] ?? 1;
  const tracking = SCRIPT_FONTS[l] ? 0 : -1.5;
  const rtl = RTL.has(l);
  const hSize = 96, sSize = 50;
  const hLine = Math.round(hSize * 1.12 * tall);
  const sLine = Math.round(sSize * 1.3 * tall);
  const hLines = wrapText(headline, 19, locale); // ~19 Latin characters per line at 96px on a 1320px canvas
  const sLines = wrapText(subhead, 30, locale);
  const padTop = 140;
  const gap = 46;
  const dir = rtl ? ' direction="rtl" unicode-bidi="embed"' : "";
  const hSpans = hLines.map((ln, i) => `<tspan x="${W / 2}" dy="${i === 0 ? 0 : hLine}">${esc(ln)}</tspan>`).join("");
  const sTop = padTop + (hLines.length - 1) * hLine + gap + sSize;
  const sSpans = sLines.map((ln, i) => `<tspan x="${W / 2}" dy="${i === 0 ? 0 : sLine}">${esc(ln)}</tspan>`).join("");
  const height = sTop + (sLines.length - 1) * sLine + 60;
  const buf = Buffer.from(`<svg width="${W}" height="${height}" xml:lang="${esc(l)}">
    <style>
      .h{ fill:${hc}; font-family:${font}; font-size:${hSize}px; font-weight:800; letter-spacing:${tracking}px; }
      .s{ fill:${hc}; opacity:.92; font-family:${font}; font-size:${sSize}px; font-weight:500; }
    </style>
    <text x="${W / 2}" y="${padTop}" text-anchor="middle" class="h"${dir}>${hSpans}</text>
    <text x="${W / 2}" y="${sTop}" text-anchor="middle" class="s"${dir}>${sSpans}</text>
  </svg>`);
  return { buf, height, headlineLines: hLines.length };
}

async function composeSlide(rawPath, headline, subhead, locale) {
  // The capture is placed below the measured text block, so it never covers the caption.
  const textTop = 60;
  const { buf: textBuf, height: textH, headlineLines } = textBlock(headline, subhead, locale);
  const imgZoneTop = textTop + textH + 40;
  const availH = H - imgZoneTop - 90;
  const maxW = Math.round(W * 0.86);
  const raw = await sharp(rawPath)
    .resize({ width: maxW, height: availH, fit: "inside", withoutEnlargement: false })
    .png().toBuffer();
  const meta = await sharp(raw).metadata();
  const left = Math.round((W - (meta.width ?? 0)) / 2);
  const top = imgZoneTop + Math.round((availH - (meta.height ?? 0)) / 2);
  const png = await sharp(backgroundSVG())
    .composite([
      { input: textBuf, top: textTop, left: 0 },
      { input: raw, top, left },
    ])
    .png()
    .toBuffer();
  return { png, headlineLines };
}

async function main() {
  const rawRoot = path.join(ROOT, "raw");
  let locales = [];
  try { locales = await fs.readdir(rawRoot); } catch { /* no captures yet */ }
  let total = 0;
  const unfit = [];
  for (const locale of locales) {
    const dir = path.join(rawRoot, locale);
    if (!(await fs.stat(dir)).isDirectory()) continue;
    const copy = await loadCopy(locale);
    const files = (await fs.readdir(dir)).filter((f) => /\.png$/i.test(f)).sort();
    const outDir = path.join(ROOT, "branded", locale);
    await fs.mkdir(outDir, { recursive: true });
    for (let i = 0; i < files.length; i++) {
      const c = copy[i] ?? {};
      const { png, headlineLines } = await composeSlide(path.join(dir, files[i]), c.headline, c.subhead, locale);
      if (headlineLines > MAX_HEADLINE_LINES) unfit.push(`${locale}/${files[i]}: headline needs ${headlineLines} lines`);
      await fs.writeFile(path.join(outDir, files[i]), png);
      total++;
    }
    console.log(`branded ${files.length} → ${locale}`);
  }
  for (const u of unfit) console.warn(`FIT ${u} (max ${MAX_HEADLINE_LINES}): shorten the caption for that language`);
  console.log(`DONE: ${total} screenshots`);
  if (unfit.length && process.env.FIT_STRICT === "1") process.exit(2);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main().catch((e) => { console.error(e); process.exit(1); });
}
