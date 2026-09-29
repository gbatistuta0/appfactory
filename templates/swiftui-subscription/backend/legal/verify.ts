// verify.ts — checks the deployed legal pages: every published document in every app language must
// answer 200 in that language (no English fallback), contain the support email and no placeholder.
// Read-only GETs, no auth.
//
//   deno run --allow-net --allow-env backend/legal/verify.ts <supabase-url> <support-email> [privacy,terms,support]
import { SUPPORTED_LOCALES } from "../../supabase/functions/_shared/locale.ts";

export interface Check {
  url: string;
  problems: string[];
}

export async function verifyLegal(
  base: string,
  email: string,
  docs: string[] = ["privacy", "terms", "support"],
  fetchImpl: typeof fetch = fetch,
): Promise<Check[]> {
  const out: Check[] = [];
  for (const doc of docs) {
    for (const lang of SUPPORTED_LOCALES) {
      const url = `${base.replace(/\/$/, "")}/functions/v1/legal/${doc}?lang=${lang}`;
      const res = await fetchImpl(url);
      const body = await res.text();
      const problems = [
        res.status !== 200 && `HTTP ${res.status}`,
        res.headers.get("Content-Language") !== lang && `served ${res.headers.get("Content-Language")}`,
        !body.includes(email) && "support email missing",
        /\{\{\s*[A-Za-z0-9_]+\s*\}\}/.test(body) && "placeholder left",
      ].filter((p): p is string => typeof p === "string");
      out.push({ url, problems });
    }
  }
  return out;
}

if (import.meta.main) {
  const [base, email, docs] = Deno.args;
  if (!base || !email) throw new Error("usage: verify.ts <supabase-url> <support-email> [privacy,terms,support]");
  const checks = await verifyLegal(base, email, docs ? docs.split(",") : undefined);
  for (const c of checks) {
    console.log(`${c.problems.length ? "FAIL" : "PASS"} ${c.url}${c.problems.length ? " → " + c.problems.join(", ") : ""}`);
  }
  const failures = checks.filter((c) => c.problems.length).length;
  console.log(failures ? `${failures} of ${checks.length} failed` : `all ${checks.length} legal URLs OK`);
  Deno.exit(failures ? 1 : 0);
}
