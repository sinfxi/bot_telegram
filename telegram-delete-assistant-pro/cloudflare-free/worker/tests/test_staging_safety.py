import pathlib, re, sqlite3, tomllib, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = tomllib.loads((ROOT / "wrangler.toml").read_text(encoding="utf-8"))
WORKER = (ROOT / "src" / "index.ts").read_text(encoding="utf-8")
SCHEMA = (ROOT.parent / "schema.sql").read_text(encoding="utf-8")
UPSERT = """
INSERT INTO telegram_updates (update_id, payload_json, status) VALUES (?, ?, 'received')
ON CONFLICT(update_id) DO UPDATE SET payload_json=excluded.payload_json, status='received',
 attempts=telegram_updates.attempts+1, last_error=NULL
WHERE telegram_updates.status='failed'
"""
class StagingConfigTests(unittest.TestCase):
 def test_worker_and_database_are_staging_only(self):
  self.assertEqual(CONFIG["name"], "fxi-telegram-edge-staging")
  binding=CONFIG["d1_databases"][0]
  self.assertEqual(binding["database_name"], "fxi_bot_stage")
  self.assertRegex(binding["database_id"], r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
  self.assertNotEqual(binding["database_id"], "00000000-0000-0000-0000-000000000000")
  self.assertNotEqual(binding["database_id"], "c31fe782-6cc2-41ff-a9a0-3e7504d3f319")
 def test_no_cron_or_production_routes(self):
  self.assertNotIn("triggers", CONFIG); self.assertNotIn("routes", CONFIG)
  self.assertTrue(CONFIG["workers_dev"])
class WebhookGuardTests(unittest.TestCase):
 def test_secret_header_and_constant_time_comparison(self):
  self.assertIn("x-telegram-bot-api-secret-token", WORKER)
  self.assertIn("safeEqual(suppliedSecret, env.TELEGRAM_WEBHOOK_SECRET)", WORKER)
 def test_payload_limit_and_update_validation(self):
  self.assertIn("1_000_000", WORKER)
  self.assertIn("Number.isSafeInteger(update.update_id)", WORKER)
  self.assertIn("temporary_storage_failure", WORKER)
 def test_no_webhook_mutation_api(self):
  self.assertNotIn("setWebhook", WORKER); self.assertNotIn("deleteWebhook", WORKER)
class RetrySemanticsTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(":memory:"); self.db.executescript(SCHEMA)
 def tearDown(self): self.db.close()
 def submit(self, uid, payload):
  self.db.execute(UPSERT,(uid,payload)); self.db.commit()
 def row(self, uid):
  return self.db.execute("SELECT payload_json,status,attempts,last_error FROM telegram_updates WHERE update_id=?",(uid,)).fetchone()
 def test_new_update(self):
  self.submit(100,'{"update_id":100}')
  self.assertEqual(self.row(100),('{"update_id":100}',"received",0,None))
 def test_failed_update_requeued_on_redelivery(self):
  self.submit(101,'{"update_id":101}')
  self.db.execute("UPDATE telegram_updates SET status='failed',attempts=1,last_error='temporary' WHERE update_id=101"); self.db.commit()
  self.submit(101,'{"update_id":101,"retry":true}')
  self.assertEqual(self.row(101),('{"update_id":101,"retry":true}',"received",2,None))
 def test_processed_duplicate_not_reset(self):
  self.submit(102,'{"update_id":102}')
  self.db.execute("UPDATE telegram_updates SET status='processed',attempts=1 WHERE update_id=102"); self.db.commit()
  self.submit(102,'{"update_id":102,"duplicate":true}')
  self.assertEqual(self.row(102),('{"update_id":102}',"processed",1,None))
if __name__ == "__main__": unittest.main()
