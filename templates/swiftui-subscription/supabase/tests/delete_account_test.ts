import { assertEquals } from "jsr:@std/assert@1";
import { createHandler } from "../functions/delete-account/handler.ts";

function setup(fail = false) {
  const deleted: string[] = [];
  const handler = createHandler({
    userIdFromJwt: (jwt) => Promise.resolve(jwt === "good" ? "u1" : null),
    deleteUser: (id) => (fail ? Promise.reject(new Error("boom")) : (deleted.push(id), Promise.resolve())),
  });
  return { handler, deleted };
}

const req = (body: unknown, jwt: string | null = "good", method = "POST") =>
  new Request("http://x/", {
    method,
    headers: jwt ? { Authorization: `Bearer ${jwt}` } : {},
    body: method === "POST" ? JSON.stringify(body) : undefined,
  });

Deno.test("delete-account: deletes the caller only after explicit confirmation", async () => {
  const { handler, deleted } = setup();
  assertEquals((await handler(req({}))).status, 400);
  assertEquals((await handler(req({ confirm: "yes" }))).status, 400);
  assertEquals(deleted, []);
  const ok = await handler(req({ confirm: "DELETE" }));
  assertEquals([ok.status, await ok.json()], [200, { deleted: true }]);
  assertEquals(deleted, ["u1"]);
});

Deno.test("delete-account: auth, method and failure paths", async () => {
  const { handler, deleted } = setup();
  assertEquals((await handler(req({ confirm: "DELETE" }, null))).status, 401);
  assertEquals((await handler(req({ confirm: "DELETE" }, "bad"))).status, 401);
  assertEquals((await handler(req(null, "good", "GET"))).status, 405);
  assertEquals(deleted, []);
  const failing = setup(true);
  const r = await failing.handler(req({ confirm: "DELETE" }));
  assertEquals([r.status, (await r.json()).error], [500, "internal_error"]);
});
