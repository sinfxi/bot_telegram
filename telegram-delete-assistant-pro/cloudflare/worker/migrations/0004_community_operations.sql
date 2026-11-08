CREATE TABLE IF NOT EXISTS community_chat_settings (
  chat_id INTEGER PRIMARY KEY,
  chat_type TEXT NOT NULL CHECK (chat_type IN ('group','supergroup','channel')),
  title TEXT NOT NULL DEFAULT '',
  settings_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(settings_json)),
  rules_text TEXT NOT NULL DEFAULT 'به اعضا احترام بگذارید؛ از اسپم و تبلیغات ناخواسته خودداری کنید.',
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS community_blocked_words (
  chat_id INTEGER NOT NULL,
  word TEXT NOT NULL COLLATE NOCASE,
  created_by INTEGER,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  PRIMARY KEY(chat_id, word)
);
CREATE TABLE IF NOT EXISTS community_warnings (
  chat_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  warning_count INTEGER NOT NULL DEFAULT 0 CHECK (warning_count >= 0),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  PRIMARY KEY(chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS community_flood_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_community_flood_lookup
  ON community_flood_events(chat_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_community_messages_recent
  ON community_messages(chat_id, created_at DESC);
INSERT OR IGNORE INTO schema_migrations(version) VALUES ('0004_community_operations');
