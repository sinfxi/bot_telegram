ALTER TABLE managers ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE managers ADD COLUMN locked_until TEXT;
CREATE INDEX IF NOT EXISTS idx_managers_active_username ON managers(is_active, username);
INSERT OR IGNORE INTO schema_migrations(version) VALUES ('0003_manager_security');
