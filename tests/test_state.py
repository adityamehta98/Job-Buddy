import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from core import state
class StatePersistenceTests(unittest.TestCase):
    def test_recency_requires_a_real_date_inside_the_window(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=2)).isoformat()
        old = (now - timedelta(hours=25)).isoformat()
        future = (now + timedelta(hours=2)).isoformat()

        self.assertTrue(state.job_age_within(recent, 24))
        self.assertFalse(state.job_age_within(old, 24))
        self.assertFalse(state.job_age_within(future, 24))
        self.assertFalse(state.job_age_within("", 24))

    def test_date_only_recency_uses_local_calendar(self):
        local_now = datetime(2026, 10, 17, 23, 48, tzinfo=timezone(timedelta(hours=-7)))
        with patch.object(state, "_local_now", return_value=local_now):
            self.assertTrue(state.job_age_within("2026-10-17", 24))
            self.assertFalse(state.job_age_within("2026-10-18", 24))
            self.assertEqual(state._today_date_string(), "2026-10-17")

    def test_migrates_legacy_state_without_third_party_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "sample.json")
            legacy = {
                "_meta": {"version": 3, "company": "sample"},
                "jobs": {
                    "private-vendor-job-url": {
                        "first_seen": 123.0,
                        "posted": "2026-10-17",
                        "title": "private vendor phrase",
                        "description": "private vendor phrase in a full description",
                    }
                },
            }
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump(legacy, handle)

            with patch.object(state.config, "SEEN_JOBS_DIR", temp_dir):
                migrated = state.load_seen_jobs("sample")
                state.save_seen_jobs("sample", migrated)

            self.assertEqual(len(migrated), 1)
            stored_key = next(iter(migrated))
            self.assertRegex(stored_key, r"^[0-9a-f]{64}$")
            self.assertEqual(
                migrated[stored_key],
                {"first_seen": 123.0, "posted": "2026-10-17"},
            )
            with open(state_path, "r", encoding="utf-8") as handle:
                serialized = handle.read()
            self.assertNotIn("private vendor phrase", serialized)
            self.assertNotIn("private-vendor-job-url", serialized)

    def test_scraper_failure_alerts_are_debounced_until_recovery(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(state.config, "SEEN_JOBS_DIR", temp_dir):
            self.assertFalse(state.record_scrape_result("apple", False, "no jobs", now=100))
            self.assertTrue(state.record_scrape_result("apple", False, "no jobs", now=200))
            self.assertFalse(state.record_scrape_result("apple", False, "no jobs", now=300))
            self.assertTrue(state.record_scrape_result(
                "apple", False, "no jobs", now=200 + state.ERROR_REMINDER_SECONDS
            ))

            self.assertFalse(state.record_scrape_result("apple", True, now=50000))
            self.assertFalse(state.record_scrape_result("apple", False, "no jobs", now=50100))

            with open(os.path.join(temp_dir, "apple.json"), encoding="utf-8") as handle:
                persisted = json.load(handle)
            self.assertEqual(persisted["_meta"]["consecutive_failures"], 1)


if __name__ == "__main__":
    unittest.main()
