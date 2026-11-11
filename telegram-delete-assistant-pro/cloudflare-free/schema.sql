-- FXI Telegram bot: Cloudflare D1 core schema
-- Target database: fxi_bot_prod
-- Migration: 0001 / fxi_core_d1_schema
-- Mirrors the active persistence operations in telegram-delete-assistant-pro/zeus_bot.py.
-- D1 uses SQLite types and TEXT timestamps; PostgreSQL JSONB/BIGSERIAL/TIMESTAMPTZ
-- and psycopg SQL must not be used against this database.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  checksum TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fxi_bot_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  data TEXT NOT NULL CHECK (json_valid(data)),
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fxi_chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  provider_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fxi_chat_user_provider_id
  ON fxi_chat_messages (user_id, provider_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_fxi_chat_user_id
  ON fxi_chat_messages (user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_fxi_chat_user_created_at
  ON fxi_chat_messages (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS fxi_community_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  sender_id INTEGER,
  sender_name TEXT NOT NULL DEFAULT '',
  username TEXT,
  body TEXT NOT NULL DEFAULT '',
  media_type TEXT NOT NULL DEFAULT 'text',
  is_bot INTEGER NOT NULL DEFAULT 0 CHECK (is_bot IN (0, 1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_fxi_community_chat_message
  ON fxi_community_messages (chat_id, message_id DESC);
CREATE INDEX IF NOT EXISTS idx_fxi_community_chat_sender_message
  ON fxi_community_messages (chat_id, sender_id, message_id DESC);
CREATE INDEX IF NOT EXISTS idx_fxi_community_chat_created_at
  ON fxi_community_messages (chat_id, created_at DESC);

-- Durable webhook idempotency/retry ledger. Store the original update JSON so
-- failed work can be retried without asking Telegram to resend the update.
CREATE TABLE IF NOT EXISTS telegram_updates (
  update_id INTEGER PRIMARY KEY,
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  status TEXT NOT NULL DEFAULT 'received'
    CHECK (status IN ('received', 'processing', 'processed', 'failed')),
  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at TEXT,
  last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_telegram_updates_status_received
  ON telegram_updates (status, received_at);

INSERT INTO schema_migrations (version, name, checksum)
VALUES ('0001', 'fxi_core_d1_schema', 'sha256:fxi-core-d1-schema-v1')
ON CONFLICT(version) DO NOTHING;
