-- Retry-safe Telegram webhook processing lease.
-- Existing staging databases apply this migration once.
ALTER TABLE fxi_py_updates ADD COLUMN claimed_at TEXT;
