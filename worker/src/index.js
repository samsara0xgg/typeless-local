// 言字 (Yana) free trial and anonymous usage stats.
//
// /v1/chat/completions  refinement on the owner's OpenAI key, for a Mac that has
//                       no key of its own: US and Canada only, only the app's
//                       refine request, a dollar budget per Mac, per network per
//                       day and per month across everyone.
// /v1/models            answers the app's connection prewarm; costs nothing.
// /stats                one row per Mac per day: counts only, never any text.
// /admin                the owner's view of installs, activity and retention: open
//                       /admin?token=... once and a cookie keeps it out of the URL.

// US dollars per million tokens: input, cached input, output (typeless_local/usage.py).
const PRICE = { input: 2.0, cached: 0.2, output: 12.0 };
// The app asks for two tokens per character, so a 15-minute dictation needs this many.
const MAX_OUTPUT_TOKENS = 8192;
const MAX_BODY_BYTES = 64 * 1024;
const TOKEN = /^[A-Za-z0-9_-]{32,128}$/;
// What a trial request may carry; everything else the app might send is dropped.
const REASONING = new Set(["none", "minimal", "low"]);
// The app's refine system prompt starts with this: the trial is not a general LLM.
const PROMPT_PREFIX = "You are the auto-editing layer of a system-wide dictation app";

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    try {
      if (pathname === "/v1/models") return json({ object: "list", data: [] });
      if (pathname === "/v1/chat/completions" && request.method === "POST") return await trial(request, env);
      if (pathname === "/stats" && request.method === "POST") return await stats(request, env);
      if (pathname === "/admin" && request.method === "GET") return await admin(request, env);
      return new Response("Not found", { status: 404 });
    } catch (err) {
      console.error(err);
      return error(500, "server_error", "Something went wrong on the trial server.");
    }
  },
};

export async function trial(request, env) {
  const token = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  if (!TOKEN.test(token)) return error(401, "trial_token", "Not a trial token.");
  const countries = (env.TRIAL_COUNTRIES || "US,CA").split(",");
  if (!countries.includes(request.cf?.country)) {
    return error(402, "trial_region", "The free trial is only available in the US and Canada.");
  }
  const caps = {
    device: Number(env.DEVICE_BUDGET_USD),
    month: Number(env.MONTHLY_BUDGET_USD),
    ip: Number(env.IP_DAILY_BUDGET_USD ?? "1"),
  };
  // A cap that does not parse would be no cap at all: refuse instead.
  if (!Object.values(caps).every((c) => Number.isFinite(c) && c >= 0)) {
    return error(402, "trial_paused", REFUSED.trial_paused);
  }
  if (!(await allowed(request, env))) return error(429, "rate_limited", "Too many requests; try again in a minute.");

  const raw = await request.text();
  const bytes = new TextEncoder().encode(raw).length;
  if (bytes > MAX_BODY_BYTES) return error(413, "too_large", "That request is too large for the free trial.");
  let sent;
  try {
    sent = JSON.parse(raw);
  } catch {
    return error(400, "bad_request", "Not a refinement request.");
  }
  const body = refineBody(sent);
  if (!body) return error(400, "bad_request", "Not a refinement request.");
  body.model = env.MODEL;

  // Reserve the worst this request can cost before spending it, so parallel
  // requests cannot overshoot a cap; the difference is given back afterwards.
  const reserve = cost({ prompt_tokens: bytes, completion_tokens: body.max_completion_tokens });
  const id = await sha256(token);
  const ip = await sha256(`${request.headers.get("CF-Connecting-IP") || "unknown"}|${env.IP_SALT || ""}`);
  const now = new Date().toISOString();
  const month = now.slice(0, 7);
  const day = now.slice(0, 10);
  const held = await reserveSpend(env, { id, ip, day, month, now }, caps, reserve);
  if (held.refused) return error(402, held.refused, REFUSED[held.refused]);

  let upstream;
  try {
    upstream = await fetch(`${env.UPSTREAM}/chat/completions`, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.OPENAI_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    await settle(env, held, 0);
    throw err;
  }
  const text = await upstream.text();
  if (!upstream.ok) {
    await settle(env, held, 0);
    console.error("upstream", upstream.status, text.slice(0, 500));
    // The owner's key out of money or refused: the trial is paused, not broken.
    // Never pass OpenAI's own text on: it can name the model.
    if ([401, 403, 429].includes(upstream.status) && (upstream.status !== 429 || /quota|credit|billing/i.test(text))) {
      return error(402, "trial_paused", REFUSED.trial_paused);
    }
    return error(502, "upstream_error", "The refinement service had a problem; try again.");
  }
  let usage;
  try {
    usage = JSON.parse(text).usage;
  } catch {
    usage = undefined;
  }
  // No usage reported: keep the worst case rather than counting it as free.
  await settle(env, held, usage ? cost(usage) : reserve);
  return new Response(text, { status: 200, headers: { "Content-Type": "application/json" } });
}

const REFUSED = {
  trial_used_up: "The free trial on this Mac is used up.",
  trial_paused: "The free trial is paused for this month.",
  trial_ip: "The free trial has reached today's limit on this network.",
};

// Only what the app's refine request uses, with limits; null when it is not one.
export function refineBody(sent) {
  if (!sent || typeof sent !== "object") return null;
  const m = sent.messages;
  const ok =
    Array.isArray(m) && m.length === 2 &&
    m[0]?.role === "system" && typeof m[0].content === "string" && m[0].content.startsWith(PROMPT_PREFIX) &&
    m[1]?.role === "user" && typeof m[1].content === "string" && m[1].content.length > 0;
  if (!ok) return null;
  const asked = Number(sent.max_completion_tokens ?? sent.max_tokens) || 512;
  const body = {
    messages: [
      { role: "system", content: m[0].content },
      { role: "user", content: m[1].content },
    ],
    max_completion_tokens: Math.max(1, Math.min(Math.floor(asked), MAX_OUTPUT_TOKENS)),
    n: 1,
    stream: false,
    store: false,
    prompt_cache_key: "yana-trial",
    prompt_cache_retention: "24h",
  };
  if (REASONING.has(sent.reasoning_effort)) body.reasoning_effort = sent.reasoning_effort;
  return body;
}

// Add ``amount`` to the Mac's, the network's and the month's spend, each only
// if it stays within its cap; on any refusal the others are given back.
export async function reserveSpend(env, keys, caps, amount) {
  const { id, ip, day, month, now } = keys;
  await env.DB.batch([
    env.DB.prepare(
      "INSERT OR IGNORE INTO trial_devices (id, spend, requests, first_seen, last_seen) VALUES (?1, 0, 0, ?2, ?2)",
    ).bind(id, now),
    env.DB.prepare("INSERT OR IGNORE INTO trial_ips (ip, day, spend) VALUES (?1, ?2, 0)").bind(ip, day),
    env.DB.prepare("INSERT OR IGNORE INTO trial_months (month, spend) VALUES (?1, 0)").bind(month),
  ]);
  const steps = [
    ["trial_used_up", "UPDATE trial_devices SET spend = spend + ?1 WHERE id = ?2 AND spend + ?1 <= ?3 RETURNING spend", [id, caps.device],
      "UPDATE trial_devices SET spend = spend - ?1 WHERE id = ?2"],
    ["trial_ip", "UPDATE trial_ips SET spend = spend + ?1 WHERE ip = ?2 AND day = ?4 AND spend + ?1 <= ?3 RETURNING spend", [ip, caps.ip, day],
      "UPDATE trial_ips SET spend = spend - ?1 WHERE ip = ?2 AND day = ?3"],
    ["trial_paused", "UPDATE trial_months SET spend = spend + ?1 WHERE month = ?2 AND spend + ?1 <= ?3 RETURNING spend", [month, caps.month],
      "UPDATE trial_months SET spend = spend - ?1 WHERE month = ?2"],
  ];
  const taken = [];
  for (const [code, take, args, give] of steps) {
    const row = await env.DB.prepare(take).bind(amount, ...args).first();
    if (!row) {
      for (const [giveSql, giveArgs] of taken) await env.DB.prepare(giveSql).bind(amount, ...giveArgs).run();
      return { refused: code };
    }
    taken.push([give, code === "trial_ip" ? [ip, day] : args.slice(0, 1)]);
  }
  return { keys, amount };
}

// Replace the reservation with what the request really cost.
export async function settle(env, held, spent) {
  const { id, ip, day, month, now } = held.keys;
  const delta = spent - held.amount;
  await env.DB.batch([
    env.DB.prepare(
      "UPDATE trial_devices SET spend = spend + ?1, requests = requests + ?3, last_seen = ?4 WHERE id = ?2",
    ).bind(delta, id, spent > 0 ? 1 : 0, now),
    env.DB.prepare("UPDATE trial_ips SET spend = spend + ?1 WHERE ip = ?2 AND day = ?3").bind(delta, ip, day),
    env.DB.prepare("UPDATE trial_months SET spend = spend + ?1 WHERE month = ?2").bind(delta, month),
  ]);
}

export function cost(usage) {
  if (!usage) return 0;
  const prompt = usage.prompt_tokens || 0;
  const cached = Math.min(usage.prompt_tokens_details?.cached_tokens || 0, prompt);
  const output = usage.completion_tokens || 0;
  return ((prompt - cached) * PRICE.input + cached * PRICE.cached + output * PRICE.output) / 1e6;
}

async function stats(request, env) {
  if (!(await allowed(request, env))) return error(429, "rate_limited", "Too many requests.");
  const raw = await request.text();
  if (raw.length > 2048) return error(413, "too_large", "Unexpected stats payload.");
  let s;
  try {
    s = JSON.parse(raw);
  } catch {
    return error(400, "bad_stats", "Unexpected stats payload.");
  }
  const ok =
    TOKEN.test(s.id || "") &&
    /^\d{4}-\d{2}-\d{2}$/.test(s.day || "") &&
    /^[\w.+-]{1,40}$/.test(s.version || "") &&
    [s.dictations, s.chars].every((n) => Number.isInteger(n) && n >= 0 && n < 1e7) &&
    typeof s.trial_spend === "number" && s.trial_spend >= 0 && s.trial_spend < 1000;
  if (!ok) return error(400, "bad_stats", "Unexpected stats payload.");
  await env.DB.prepare(
    "INSERT OR REPLACE INTO daily_stats (id, day, version, dictations, chars, trial_spend) VALUES (?, ?, ?, ?, ?, ?)",
  )
    .bind(s.id, s.day, s.version, s.dictations, s.chars, s.trial_spend)
    .run();
  return json({ ok: true });
}

async function admin(request, env) {
  const url = new URL(request.url);
  const cookie = /(?:^|;\s*)yana_admin=([^;]+)/.exec(request.headers.get("Cookie") || "")?.[1] || "";
  const header = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  const query = url.searchParams.get("token") || "";
  const given = header || cookie || query;
  if (!env.ADMIN_TOKEN || !(await sameSecret(given, env.ADMIN_TOKEN))) return new Response("Not found", { status: 404 });
  if (query) {
    // Swap the token in the address bar (and in history and logs) for a cookie.
    return new Response(null, {
      status: 303,
      headers: {
        Location: "/admin",
        "Set-Cookie": `yana_admin=${encodeURIComponent(query)}; Path=/admin; HttpOnly; Secure; SameSite=Strict; Max-Age=31536000`,
      },
    });
  }
  const q = async (sql) => (await env.DB.prepare(sql).all()).results;
  const [totals] = await q(
    "SELECT COUNT(DISTINCT id) AS installs, " +
      "COUNT(DISTINCT CASE WHEN day >= date('now', '-6 days') AND dictations > 0 THEN id END) AS wau, " +
      "COUNT(DISTINCT CASE WHEN day >= date('now', '-6 days') THEN id END) AS open_7d FROM daily_stats",
  );
  const days = await q(
    "SELECT day, COUNT(DISTINCT CASE WHEN dictations > 0 THEN id END) AS dau, COUNT(DISTINCT id) AS open, " +
      "SUM(dictations) AS dictations, SUM(chars) AS chars, " +
      "ROUND(1.0 * SUM(dictations) / MAX(1, COUNT(DISTINCT CASE WHEN dictations > 0 THEN id END)), 1) AS per_user " +
      "FROM daily_stats WHERE day >= date('now', '-29 days') GROUP BY day ORDER BY day DESC",
  );
  // A Mac counts as retained when it dictated again 7 or more days after it first reported.
  const cohorts = await q(
    "WITH first AS (SELECT id, MIN(day) AS d0 FROM daily_stats GROUP BY id) " +
      "SELECT strftime('%Y-W%W', f.d0) AS week, COUNT(*) AS new_macs, " +
      "SUM(EXISTS (SELECT 1 FROM daily_stats s WHERE s.id = f.id AND s.dictations > 0 AND s.day >= date(f.d0, '+7 days'))) AS retained, " +
      "SUM(f.d0 <= date('now', '-7 days')) AS eligible " +
      "FROM first f GROUP BY week ORDER BY week DESC LIMIT 12",
  );
  const versions = await q(
    "SELECT version, COUNT(DISTINCT id) AS macs FROM daily_stats WHERE day >= date('now', '-6 days') GROUP BY version ORDER BY macs DESC",
  );
  const [trialTotals] = await q(
    `SELECT COUNT(*) AS macs, ROUND(SUM(spend), 2) AS spend, SUM(spend >= ${Number(env.DEVICE_BUDGET_USD)}) AS used_up FROM trial_devices`,
  );
  const months = await q("SELECT month, ROUND(spend, 2) AS spend FROM trial_months ORDER BY month DESC LIMIT 6");

  const page = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Yana stats</title>
<style>body{font:14px -apple-system,system-ui,sans-serif;margin:24px;max-width:860px;color:#1d1d1f}
table{border-collapse:collapse;margin:8px 0 24px}td,th{padding:4px 12px;border-bottom:1px solid #ddd;text-align:right}
th:first-child,td:first-child{text-align:left}.big{font-size:28px;font-weight:600}.row{display:flex;gap:32px;margin-bottom:24px}</style>
<h1>言字 (Yana)</h1>
<div class="row">
<div><div class="big">${totals.installs}</div>Macs ever reported</div>
<div><div class="big">${totals.wau}</div>dictated in last 7 days</div>
<div><div class="big">${totals.open_7d}</div>running in last 7 days</div>
<div><div class="big">$${trialTotals.spend ?? 0}</div>trial spend, ${trialTotals.macs} Macs, ${trialTotals.used_up ?? 0} used up</div>
</div>
<h2>Last 30 days</h2>${table(days, ["day", "dau", "open", "dictations", "per_user", "chars"])}
<h2>7-day retention by first week</h2>
<p>Retained: dictated again 7+ days after first reporting. Eligible: first reported at least 7 days ago.</p>
${table(cohorts.map((c) => ({ ...c, rate: c.eligible ? `${Math.round((100 * c.retained) / c.eligible)}%` : "–" })), ["week", "new_macs", "eligible", "retained", "rate"])}
<h2>Versions, last 7 days</h2>${table(versions, ["version", "macs"])}
<h2>Trial spend by month (cap $${env.MONTHLY_BUDGET_USD})</h2>${table(months, ["month", "spend"])}`;
  return new Response(page, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}

function table(rows, cols) {
  const esc = (v) => String(v ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  const head = cols.map((c) => `<th>${c.replace("_", " ")}</th>`).join("");
  const body = rows.map((r) => `<tr>${cols.map((c) => `<td>${esc(r[c])}</td>`).join("")}</tr>`).join("");
  return `<table><tr>${head}</tr>${body || `<tr><td colspan="${cols.length}">No data yet</td></tr>`}</table>`;
}

async function allowed(request, env) {
  if (!env.PER_IP) return true;
  const { success } = await env.PER_IP.limit({ key: request.headers.get("CF-Connecting-IP") || "unknown" });
  return success;
}

async function sha256(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function sameSecret(a, b) {
  return (await sha256(a)) === (await sha256(b));
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

function error(status, code, message) {
  return json({ error: { code, message, type: "yana_trial" } }, status);
}
