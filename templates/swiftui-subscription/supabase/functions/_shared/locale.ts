// locale.ts — map any client locale tag to one of the app's languages (app.gen.ts).
import { SUPPORTED_LOCALES } from "./app.gen.ts";

export { SUPPORTED_LOCALES };
export type AppLocale = typeof SUPPORTED_LOCALES[number];

const FALLBACK = SUPPORTED_LOCALES[0] as AppLocale;

/** Legacy and macro-language codes iOS still sends: no/nn → nb, iw → he, in → id. */
const ALIASES: Record<string, string> = { no: "nb", nn: "nb", iw: "he", in: "id", ji: "yi" };

/** Chinese by script: zh-Hant for Hant or Taiwan / Hong Kong / Macau, else zh-Hans (zh-CN, zh-SG, bare zh). */
function chineseScript(parts: string[]): string {
  return parts.includes("hant") || parts.some((p) => ["tw", "hk", "mo"].includes(p)) ? "zh-hant" : "zh-hans";
}

/** Lower-case language (or Chinese script) of a tag: "zh-TW" → "zh-hant", "no" → "nb", "de-AT" → "de". */
export function canonicalLanguage(tag: string): string {
  const parts = tag.trim().replace(/_/g, "-").toLowerCase().split("-").filter(Boolean);
  const lang = ALIASES[parts[0]] ?? parts[0] ?? "";
  return lang === "zh" ? chineseScript(parts) : lang;
}

/**
 * Strict match: an exact tag first ("pt-BR"), then the script/alias form ("zh-TW" → "zh-Hant",
 * "no" → "nb", "iw" → "he"), then the language alone ("tr-TR" → "tr", "es-MX" → "es", "pt_PT" →
 * "pt-BR" when that is the only Portuguese shipped). A language the app does not ship → null.
 */
export function matchLocale(tag: unknown): AppLocale | null {
  if (typeof tag !== "string" || !tag.trim()) return null;
  const norm = tag.trim().replace(/_/g, "-").toLowerCase();
  const exact = SUPPORTED_LOCALES.find((l) => l.toLowerCase() === norm);
  if (exact) return exact;
  const lang = ALIASES[norm.split("-")[0]] ?? norm.split("-")[0];
  const canonical = canonicalLanguage(norm);
  return SUPPORTED_LOCALES.find((l) => l.toLowerCase() === canonical) ??
    SUPPORTED_LOCALES.find((l) => l.toLowerCase() === lang) ??
    SUPPORTED_LOCALES.find((l) => l.toLowerCase().split("-")[0] === lang) ??
    null;
}

/** Languages not written in Latin letters: the model is asked for their own script (without it,
 * ru/ar/ja/zh/th/el answers came back transliterated or in the input's language). */
const NATIVE_SCRIPT = new Set([
  "ar",
  "fa",
  "ur",
  "he",
  "hi",
  "mr",
  "bn",
  "ta",
  "te",
  "gu",
  "kn",
  "ml",
  "pa",
  "th",
  "lo",
  "km",
  "my",
  "ja",
  "ko",
  "zh",
  "ru",
  "uk",
  "be",
  "bg",
  "sr",
  "mk",
  "kk",
  "el",
  "ka",
  "hy",
  "am",
]);

export function usesNativeScript(locale: string): boolean {
  return NATIVE_SCRIPT.has(locale.toLowerCase().split(/[-_]/)[0]);
}

/**
 * The prompt's language rule. Always: write in the user's language and name things in it, never in
 * the language of the photo or the text (e.g. a Turkish dish name leaked into ja/ko/id answers).
 * Non-Latin languages additionally get their own script, never a transliteration.
 */
export function languageRule(locale: string): string {
  const name = languageName(locale);
  const script = usesNativeScript(locale)
    ? `, in ${name} script (never transliterated into Latin letters)`
    : "";
  return `write every text field in ${name}${script}. Name things in ${name}, even when the photo or ` +
    `the user's text names them in another language.`;
}

/** Like matchLocale, but anything unknown or missing → the fallback language. */
export function normalizeLocale(tag: unknown): AppLocale {
  return matchLocale(tag) ?? FALLBACK;
}

/** English name of a language for the model prompt ("pt-BR" → "Brazilian Portuguese"). */
export function languageName(locale: string): string {
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(locale) ?? locale;
  } catch {
    return locale;
  }
}
