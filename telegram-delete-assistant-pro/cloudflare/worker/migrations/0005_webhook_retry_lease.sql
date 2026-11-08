ALTER TABLE telegram_updates ADD COLUMN processing_started_at TEXT;
CREATE INDEX IF NOT EXISTS idx_telegram_updates_processing_started ON telegram_updates(processing_status, processing_started_at);
INSERT OR IGNORE INTO schema_migrations(version) VALUES ('0005_webhook_retry_lease');
