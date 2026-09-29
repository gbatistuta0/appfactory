import { assertEquals } from "jsr:@std/assert@1";
import { mapEvent } from "./map.ts";

Deno.test("initial purchase → +revenue", async () => {
  const ev = JSON.parse(await Deno.readTextFile(new URL("./fixtures/initial_purchase.json", import.meta.url))).event;
  const row = mapEvent(ev, "myapp");
  assertEquals(row.sign, 1);
  assertEquals(row.is_trial, false);
  assertEquals(typeof row.price_usd, "number");
  assertEquals(row.user_id, ev.app_user_id);
});

Deno.test("trial start → not revenue", async () => {
  const ev = JSON.parse(await Deno.readTextFile(new URL("./fixtures/trial_started.json", import.meta.url))).event;
  assertEquals(mapEvent(ev, "myapp").is_trial, true);
});

Deno.test("cancellation/refund → sign -1", async () => {
  const ev = JSON.parse(await Deno.readTextFile(new URL("./fixtures/cancellation.json", import.meta.url))).event;
  assertEquals(mapEvent(ev, "myapp").sign, -1);
});
