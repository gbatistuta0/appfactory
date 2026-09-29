// prepare.ts — builds the eval set (data/cases.json) from labelled local files. Free: no network,
// no API calls. Images are converted the way the iOS app sends them (JPEG q80, long edge ≤ 1024,
// no metadata) with macOS `sips`.
//
//   deno run --allow-read --allow-write --allow-run backend/eval/prepare.ts [inbox=data/inbox] [out=cases.json]
//
// Inbox layout:
//   <name>.jpg|.jpeg|.png|.heic   one photo case each
//   <name>.json                   its ground truth ("expected", app-defined; see score_app.ts)
//   text.json                     optional text cases: [{"id": "...", "text": "...", "expected": {...}}]
// A public dataset (e.g. Nutrition5k, CC BY 4.0) can be downloaded into the inbox first; record
// its source and licence in EVAL.md.
import type { Case } from "./score.ts";

const HERE = new URL("./", import.meta.url);
const IMAGE_EXT = /\.(jpe?g|png|heic)$/i;

export function caseId(fileName: string): string {
  return fileName.replace(IMAGE_EXT, "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-|-$/g, "");
}

export async function buildCases(
  inbox: URL,
  convert: (src: string, dst: string) => Promise<void>,
  imagesDir: URL,
): Promise<Case[]> {
  const cases: Case[] = [];
  const names: string[] = [];
  for await (const e of Deno.readDir(inbox)) if (e.isFile) names.push(e.name);
  names.sort();
  for (const name of names.filter((n) => IMAGE_EXT.test(n))) {
    const id = caseId(name);
    const sidecar = names.find((n) => n === name.replace(IMAGE_EXT, ".json"));
    const expected = sidecar ? JSON.parse(await Deno.readTextFile(new URL(sidecar, inbox))) : {};
    await convert(new URL(name, inbox).pathname, new URL(`${id}.jpg`, imagesDir).pathname);
    cases.push({ id, mode: "photo", image: `images/${id}.jpg`, text: null, expected });
  }
  if (names.includes("text.json")) {
    const rows = JSON.parse(await Deno.readTextFile(new URL("text.json", inbox))) as Array<Record<string, unknown>>;
    for (const r of rows) {
      cases.push({ id: String(r.id), mode: "text", image: null, text: String(r.text), expected: (r.expected ?? {}) as Record<string, unknown> });
    }
  }
  const ids = cases.map((c) => c.id);
  const dup = ids.filter((id, i) => ids.indexOf(id) !== i);
  if (dup.length) throw new Error(`duplicate case ids: ${[...new Set(dup)].join(", ")}`);
  return cases;
}

async function sips(src: string, dst: string): Promise<void> {
  const r = await new Deno.Command("sips", {
    args: ["-s", "format", "jpeg", "-s", "formatOptions", "80", "-Z", "1024", src, "--out", dst],
    stdout: "null", stderr: "piped",
  }).output();
  if (!r.success) throw new Error(new TextDecoder().decode(r.stderr));
}

if (import.meta.main) {
  const inbox = new URL(`${(Deno.args[0] ?? "data/inbox").replace(/\/?$/, "/")}`, HERE);
  const out = Deno.args[1] ?? "cases.json";
  const images = new URL("data/images/", HERE);
  await Deno.mkdir(images, { recursive: true });
  const cases = await buildCases(inbox, sips, images);
  await Deno.writeTextFile(new URL(`data/${out}`, HERE), JSON.stringify({
    source: "local labelled set (see EVAL.md)", created: new Date().toISOString(), cases,
  }, null, 2) + "\n");
  console.log(`wrote ${cases.length} cases to backend/eval/data/${out}`);
}
