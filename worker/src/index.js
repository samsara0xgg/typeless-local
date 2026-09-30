// 言字 (Yana) free trial and anonymous usage stats.
//
// /v1/chat/completions  refinement on the owner's OpenAI key, for a Mac that has
//                       no key of its own: North America only, a dollar budget
//                       per Mac and a monthly cap across everyone.
// /v1/models            answers the app's connection prewarm; costs nothing.
// /stats                one row per Mac per day: counts only, never any text.
// /admin?token=...      the owner's view of installs, activity and retention.

// US dollars per million tokens: input, cached input, output (typeless_local/usage.py).
const PRICE = { input: 2.0, cached: 0.2, output: 12.0 };
const MAX_OUTPUT_TOKENS = 4096;
const TOKEN = /^[A-Za-z0-9_-]{32,128}$/;

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

async function trial(request, env) {
  const token = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  if (!TOKEN.test(token)) return error(401, "trial_token", "Not a trial token.");
  const countries = (env.TRIAL_COUNTRIES || "US,CA").split(",");
  if (!countries.includes(request.cf?.country)) {
    return error(402, "trial_region", "The free trial is only available in the US and Canada.");
  }
  if (!(await allowed(request, env))) return error(429, "rate_limited", "Too many requests; try again in a minute.");

  const id = await sha256(token);
  const month = new Date().toISOString().slice(0, 7);
  const device = await env.DB.prepare("SELECT spend FROM trial_devices WHERE id = ?").bind(id).first();
  if (device && device.spend >= Number(env.DEVICE_BUDGET_USD)) {
    return error(402, "trial_used_up", "The free trial on this Mac is used up.");
  }
  const total = await env.DB.prepare("SELECT spend FROM trial_months WHERE month = ?").bind(month).first();
  if (total && total.spend >= Number(env.MONTHLY_BUDGET_USD)) {
    return error(402, "trial_paused", "The free trial is paused for this month.");
  }

  const body = await request.json();
  body.model = env.MODEL;
  body.stream = false;
  body.max_completion_tokens = Math.min(Number(body.max_completion_tokens) || 512, MAX_OUTPUT_TOKENS);
  delete body.max_tokens;
  body.prompt_cache_key = "yana-trial";
  body.prompt_cache_retention = "24h";
  const upstream = await fetch(`${env.UPSTREAM}/chat/completions`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.OPENAI_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await upstream.text();
  if (upstream.ok) {
    const spent = cost(JSON.parse(text).usage);
    const now = new Date().toISOString();
    await env.DB.batch([
      env.DB.prepare(
        "INSERT INTO trial_devices (id, spend, requests, first_seen, last_seen) VALUES (?1, ?2, 1, ?3, ?3) " +
          "ON CONFLICT(id) DO UPDATE SET spend = spend + ?2, requests = requests + 1, last_seen = ?3",
      ).bind(id, spent, now),
      env.DB.prepare(
        "INSERT INTO trial_months (month, spend) VALUES (?1, ?2) ON CONFLICT(month) DO UPDATE SET spend = spend + ?2",
      ).bind(month, spent),
    ]);
  }
  return new Response(text, { status: upstream.status, headers: { "Content-Type": "application/json" } });
}

function cost(usage) {
  if (!usage) return 0;
  const prompt = usage.prompt_tokens || 0;
  const cached = Math.min(usage.prompt_tokens_details?.cached_tokens || 0, prompt);
  const output = usage.completion_tokens || 0;
  return ((prompt - cached) * PRICE.input + cached * PRICE.cached + output * PRICE.output) / 1e6;
}

async function stats(request, env) {
  if (!(await allowed(request, env))) return error(429, "rate_limited", "Too many requests.");
  const s = await request.json();
  const ok =
    TOKEN.test(s.id || "") &&
    /^\d{4}-\d{2}-\d{2}$/.test(s.day || "") &&
    /^[\w.+-]{1,40}$/.test(s.version || "") &&
    [s.dictations, s.chars].every((n) => Number.isInteger(n) && n >= 0 && n < 1e7) &&
    typeof s.trial_spend === "number" && s.trial_spend >= 0 && s.trial_spend < 1000;
  if (!ok) return error(400, "bad_stats", "Unexpected stats payload.");
  await env.DB.prepare(
    "INSERT OR REPLACE INTO daily_stats (id, day, version, dictations, chars, trial_spend, country) VALUES (?, ?, ?, ?, ?, ?, ?)",
  )
    .bind(s.id, s.day, s.version, s.dictations, s.chars, s.trial_spend, request.cf?.country || null)
    .run();
  return json({ ok: true });
}

async function admin(request, env) {
  const given = new URL(request.url).searchParams.get("token") || "";
  if (!env.ADMIN_TOKEN || !(await sameSecret(given, env.ADMIN_TOKEN))) return new Response("Not found", { status: 404 });
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
