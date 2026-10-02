-- Free-trial spend and anonymous daily usage for 言字 (Yana).
-- Apply with: npx wrangler d1 execute yana --remote --file=schema.sql

CREATE TABLE IF NOT EXISTS trial_devices (
  id TEXT PRIMARY KEY,          -- SHA-256 of the per-Mac trial token, never the token
  spend REAL NOT NULL DEFAULT 0,
  requests INTEGER NOT NULL DEFAULT 0,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trial_ips (
  ip TEXT NOT NULL,             -- SHA-256 of the client IP and a salt, never the IP
  day TEXT NOT NULL,            -- YYYY-MM-DD, UTC
  spend REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (ip, day)
);

CREATE TABLE IF NOT EXISTS trial_months (
  month TEXT PRIMARY KEY,       -- YYYY-MM, UTC
  spend REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_stats (
  id TEXT NOT NULL,             -- random per-Mac stats id, unrelated to the trial token
  day TEXT NOT NULL,            -- YYYY-MM-DD, the Mac's local date
  version TEXT NOT NULL,
  dictations INTEGER NOT NULL,
  chars INTEGER NOT NULL,
  trial_spend REAL NOT NULL,
  country TEXT,                 -- no longer written
  PRIMARY KEY (id, day)
);

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,     -- ISO time, UTC
  message TEXT NOT NULL,
  email TEXT NOT NULL DEFAULT '',   -- optional reply address the user typed
  version TEXT NOT NULL DEFAULT '',
  macos TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  spoken_language TEXT NOT NULL DEFAULT '',
  ui_language TEXT NOT NULL DEFAULT '',
  diagnostics TEXT NOT NULL DEFAULT ''  -- only when the user ticked "attach diagnostics"
);
