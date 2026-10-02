// node --test worker/test  (node:sqlite stands in for D1; nothing is deployed)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import worker from "../src/index.js";

function d1() {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  const stmt = (sql, args = []) => ({
    bind: (...a) => stmt(sql, a),
    all: async () => ({ results: db.prepare(sql).all(...args) }),
    first: async () => db.prepare(sql).get(...args) ?? null,
    run: async () => db.prepare(sql).run(...args),
  });
  return { raw: db, prepare: (sql) => stmt(sql) };
}

const note = (extra = {}) => ({
  message: "dictation stops after a minute",
  email: "me@example.com",
  version: "0.4.0",
  macos: "15.4",
  model: "Mac14,2",
  spoken_language: "zh",
  ui_language: "en",
  ...extra,
});
const send = (body, env) =>
  worker.fetch(new Request("https://w/feedback", { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body) }), env);
const rows = (env) => env.DB.raw.prepare("SELECT * FROM feedback ORDER BY id").all();

test("feedback is stored with its fields and no country", async () => {
  const env = { DB: d1() };
  assert.equal((await send(note({ diagnostics: "summary\nlog" }), env)).status, 200);
  const [row] = rows(env);
  assert.equal(row.message, "dictation stops after a minute");
  assert.equal(row.email, "me@example.com");
  assert.equal(row.macos, "15.4");
  assert.equal(row.diagnostics, "summary\nlog");
  assert.ok(!("country" in row));
});

test("bad feedback is refused and nothing is stored", async () => {
  const env = { DB: d1() };
  const bad = [
    note({ message: "   " }),
    note({ message: "x".repeat(4001) }),
    note({ email: "not an email" }),
    note({ email: `${"a".repeat(200)}@b.co` }),
    note({ version: "v".repeat(101) }),
    note({ model: 5 }),
    note({ diagnostics: "d".repeat(48 * 1024 + 1) }),
    "{not json",
    "[]",
  ];
  for (const body of bad) assert.equal((await send(body, env)).status, 400, JSON.stringify(body).slice(0, 60));
  assert.equal((await send("x".repeat(70 * 1024), env)).status, 413);
  assert.equal(rows(env).length, 0);
  assert.equal((await send(note({ email: "" }), env)).status, 200); // the email is optional
});

test("the rate limiter turns feedback away", async () => {
  const env = { DB: d1(), PER_IP: { limit: async () => ({ success: false }) } };
  assert.equal((await send(note(), env)).status, 429);
  assert.equal(rows(env).length, 0);
});

test("the admin page lists feedback newest first, escaped, diagnostics collapsed", async () => {
  const env = { DB: d1(), ADMIN_TOKEN: "t", DEVICE_BUDGET_USD: "0.5", MONTHLY_BUDGET_USD: "20" };
  await send(note({ message: "oldest" }), env);
  await send(note({ message: "<script>alert(1)</script> & \"q\"", diagnostics: "log <b>" }), env);
  const res = await worker.fetch(new Request("https://w/admin", { headers: { Authorization: "Bearer t" } }), env);
  const page = await res.text();
  assert.match(page, /&lt;script&gt;alert\(1\)&lt;\/script&gt; &amp; &quot;q&quot;/);
  assert.doesNotMatch(page, /<script>alert/);
  assert.match(page, /<details><summary>diagnostics<\/summary><pre[^>]*>log &lt;b&gt;/);
  assert.ok(page.indexOf("&lt;script&gt;") < page.indexOf("oldest"));
});
