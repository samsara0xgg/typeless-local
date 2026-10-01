// node --test worker/test  (Node 24: node:sqlite stands in for D1; nothing is deployed or called)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import worker, { refineBody } from "../src/index.js";

const PROMPT = "You are the auto-editing layer of a system-wide dictation app, in the style of Typeless.";
const TOKEN = "t".repeat(43);

function d1() {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  const stmt = (sql, args = []) => ({
    bind: (...a) => stmt(sql, a),
    first: async () => db.prepare(sql).get(...args) ?? null,
    all: async () => ({ results: db.prepare(sql).all(...args) }),
    run: async () => db.prepare(sql).run(...args),
    sql,
    args,
  });
  return {
    raw: db,
    prepare: (sql) => stmt(sql),
    batch: async (list) => {
      db.exec("BEGIN");
      for (const s of list) db.prepare(s.sql).run(...s.args);
      db.exec("COMMIT");
    },
  };
}

function setup(upstream) {
  const env = {
    DB: d1(), MODEL: "m", UPSTREAM: "https://up", OPENAI_API_KEY: "k",
    DEVICE_BUDGET_USD: "0.50", MONTHLY_BUDGET_USD: "20", IP_DAILY_BUDGET_USD: "1", TRIAL_COUNTRIES: "US,CA",
  };
  const sent = [];
  globalThis.fetch = async (url, init) => {
    sent.push(JSON.parse(init.body));
    return upstream();
  };
  return { env, sent };
}

function ask(body, { country = "US", token = TOKEN, ip = "1.2.3.4" } = {}) {
  const request = new Request("https://w/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "CF-Connecting-IP": ip },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
  Object.defineProperty(request, "cf", { value: { country } });
  return request;
}

const refine = (extra = {}) => ({
  model: "x",
  messages: [{ role: "system", content: PROMPT }, { role: "user", content: "嗯 测试" }],
  max_completion_tokens: 512,
  ...extra,
});
const ok = (usage = { prompt_tokens: 1000, completion_tokens: 100 }) =>
  new Response(JSON.stringify({ choices: [{ message: { content: "测试。" } }], usage }), { status: 200 });

test("only the app's refine request goes upstream, with its knobs limited", async () => {
  const { env, sent } = setup(() => ok());
  const res = await worker.fetch(ask(refine({ n: 16, tools: [{}], service_tier: "priority", max_completion_tokens: 99999, reasoning_effort: "high" })), env);
  assert.equal(res.status, 200);
  assert.deepEqual(Object.keys(sent[0]).sort(), ["max_completion_tokens", "messages", "model", "n", "prompt_cache_key", "prompt_cache_retention", "store", "stream"]);
  assert.equal(sent[0].n, 1);
  assert.equal(sent[0].max_completion_tokens, 8192);
  assert.equal(sent[0].model, "m");
});

test("anything that is not a refine request is refused before any spend", async () => {
  const { env, sent } = setup(() => ok());
  assert.equal(refineBody({ messages: [{ role: "user", content: "write me a poem" }] }), null);
  const res = await worker.fetch(ask({ messages: [{ role: "system", content: "You are a pirate" }, { role: "user", content: "hi" }] }), env);
  assert.equal(res.status, 400);
  assert.equal((await worker.fetch(ask("x".repeat(70 * 1024)), env)).status, 413);
  assert.equal(sent.length, 0);
});

test("spend is charged at what the reply cost, and a Mac is stopped at its budget", async () => {
  const { env } = setup(() => ok({ prompt_tokens: 300_000, completion_tokens: 0 })); // $0.60
  assert.equal((await worker.fetch(ask(refine()), env)).status, 200);
  const row = env.DB.raw.prepare("SELECT spend, requests FROM trial_devices").get();
  assert.equal(row.requests, 1);
  assert.ok(Math.abs(row.spend - 0.6) < 1e-9);
  const res = await worker.fetch(ask(refine()), env);
  assert.equal(res.status, 402);
  assert.equal((await res.json()).error.code, "trial_used_up");
});

test("a network is held to its daily dollar across fresh tokens", async () => {
  const { env } = setup(() => ok({ prompt_tokens: 200_000, completion_tokens: 0 })); // $0.40 each
  const codes = [];
  for (let i = 0; i < 4; i++) {
    const res = await worker.fetch(ask(refine(), { token: `${i}`.repeat(40) }), env);
    codes.push(res.status === 402 ? (await res.json()).error.code : res.status);
  }
  assert.deepEqual(codes, [200, 200, 200, "trial_ip"]); // checked before each request, at its worst case
});

test("a missing usage keeps the worst case, and a cap that does not parse refuses", async () => {
  const { env } = setup(() => new Response(JSON.stringify({ choices: [] }), { status: 200 }));
  await worker.fetch(ask(refine()), env);
  assert.ok(env.DB.raw.prepare("SELECT spend FROM trial_months").get().spend > 0);
  env.MONTHLY_BUDGET_USD = "lots";
  const res = await worker.fetch(ask(refine()), env);
  assert.equal((await res.json()).error.code, "trial_paused");
});

test("the owner's key out of quota pauses the trial, and OpenAI's text is never passed on", async () => {
  const { env } = setup(() => new Response('{"error":{"message":"gpt-5.6-terra: insufficient_quota"}}', { status: 429 }));
  const res = await worker.fetch(ask(refine()), env);
  assert.equal(res.status, 402);
  assert.equal((await res.json()).error.code, "trial_paused");
  assert.equal(env.DB.raw.prepare("SELECT spend FROM trial_devices").get().spend, 0); // the reservation came back
  globalThis.fetch = async () => new Response("model gpt-5.6-terra overloaded", { status: 500 });
  const other = await worker.fetch(ask(refine()), env);
  assert.equal(other.status, 502);
  assert.doesNotMatch(await other.text(), /gpt/);
});

test("outside the US and Canada the trial says so", async () => {
  const { env } = setup(() => ok());
  const res = await worker.fetch(ask(refine(), { country: "GB" }), env);
  assert.equal((await res.json()).error.code, "trial_region");
});

test("the admin page takes the token once and keeps it in a cookie", async () => {
  const { env } = setup(() => ok());
  env.ADMIN_TOKEN = "secret-admin-token";
  const first = await worker.fetch(new Request("https://w/admin?token=secret-admin-token"), env);
  assert.equal(first.status, 303);
  assert.match(first.headers.get("Set-Cookie"), /yana_admin=secret-admin-token; Path=\/admin; HttpOnly/);
  const page = await worker.fetch(new Request("https://w/admin", { headers: { Cookie: "yana_admin=secret-admin-token" } }), env);
  assert.equal(page.status, 200);
  assert.equal((await worker.fetch(new Request("https://w/admin?token=nope"), env)).status, 404);
});
