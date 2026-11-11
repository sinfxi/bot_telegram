-- Compatibility marker retained for databases that already received
-- claimed_at in 0001_initial.sql. The column is part of the initial schema,
-- so this migration must remain a no-op to avoid duplicate-column failures.
SELECT 1;
