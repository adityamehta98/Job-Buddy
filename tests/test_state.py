import json
import os
import tempfile
import unittest
from unittest.mock import patch

import state


class StatePersistenceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
