CREATE TABLE IF NOT EXISTS fxi_py_updates (
    update_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'received',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS fxi_py_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fxi_py_messages_chat
    ON fxi_py_messages(chat_id, id DESC);

CREATE TABLE IF NOT EXISTS fxi_py_channel_posts (
    chat_id TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    posted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(chat_id, message_id)
);
