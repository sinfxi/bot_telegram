-- FXI Telegram Assistant — initial D1 schema proposal
-- SQLite / Cloudflare D1. Apply only after review and migration tests.
-- This schema intentionally does not import or delete production data.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS telegram_updates (
  update_id INTEGER PRIMARY KEY,
  received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  status TEXT NOT NULL DEFAULT 'received'
    CHECK (status IN ('received','processing','processed','failed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_telegram_updates_status_received
  ON telegram_updates(status, received_at);

CREATE TABLE IF NOT EXISTS bot_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  data_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS users (
  telegram_user_id INTEGER PRIMARY KEY,
  username TEXT,
  display_name TEXT NOT NULL DEFAULT '',
  profile_json TEXT NOT NULL DEFAULT '{}',
  first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS communities (
  chat_id INTEGER PRIMARY KEY,
  chat_type TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  username TEXT,
  settings_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS community_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  sender_id INTEGER,
  sender_name TEXT NOT NULL DEFAULT '',
  username TEXT,
  body TEXT NOT NULL DEFAULT '',
  media_type TEXT NOT NULL DEFAULT 'text',
  is_bot INTEGER NOT NULL DEFAULT 0 CHECK (is_bot IN (0,1)),
  created_at TEXT NOT NULL,
  UNIQUE(chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_community_messages_chat_message
  ON community_messages(chat_id, message_id DESC);
CREATE INDEX IF NOT EXISTS idx_community_messages_chat_sender_message
  ON community_messages(chat_id, sender_id, message_id DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  provider_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_user_provider_id
  ON chat_messages(user_id, provider_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_user_id
  ON chat_messages(user_id, id DESC);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL,
  details TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_events_created
  ON audit_events(created_at DESC);
