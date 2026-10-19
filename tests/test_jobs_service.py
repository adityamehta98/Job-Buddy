import unittest
import os
import tempfile
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core import jobs_service
from core import jd_fetch
class JobsServiceTests(unittest.TestCase):
    @patch("core.jobs_service.is_applied", return_value=False)
    @patch("core.jobs_service.list_companies", return_value=[])
    @patch("core.jobs_service.resume_store.active_resume_text", return_value="Python and AWS")
    @patch("core.jobs_service._fetch_custom_jobs")
    @patch("core.jobs_service.list_custom_companies")
    def test_filters_non_us_and_scores_full_jd(
        self, custom_companies, fetch_jobs, _resume, _builtins, _applied
    ):
        custom_companies.return_value = [
            {"name": "Example", "url": "https://example.test", "ats": "greenhouse", "token": "example"}
        ]
        common = {
            "team": "Platform",
            "posted": "2026-10-17",
            "description": "Build Python and SQL services on AWS. " * 3,
            "url": "https://example.test/job",
        }
        fetch_jobs.return_value = [
            {"key": "us", "title": "Software Engineer", "location": "Phoenix, AZ", **common},
            {"key": "uk", "title": "Software Engineer", "location": "London, UK", **common},
        ]

        result = jobs_service.get_all_jobs(include_builtins=False)

        self.assertEqual(result["filtered_non_us"], 1)
        self.assertEqual(len(result["jobs"]), 1)
        job = result["jobs"][0]
        self.assertEqual(job["location"], "Phoenix, AZ")
        self.assertEqual(job["match"], 67)
        self.assertEqual(job["matched_count"], 2)
        self.assertEqual(job["jd_skill_count"], 3)
        self.assertEqual(job["missing"], ["sql"])
        self.assertTrue(job["keyword_details"])

    @patch("core.jobs_service.is_applied", return_value=False)
    @patch("core.jobs_service.resume_store.active_resume_text", return_value="")
    @patch("core.jobs_service.list_custom_companies", return_value=[])
    @patch("core.jobs_service.list_companies", return_value=["apple"])
    @patch("core.jobs_service._fetch_builtin_jobs")
    @patch("core.jobs_service.config.get_company_runtime")
    def test_fetches_builtin_companies_live(
        self, runtime, fetch_builtins, _companies, _custom, _resume, _applied
    ):
        today = jobs_service._local_today().isoformat()
        runtime.return_value = SimpleNamespace(display_name="Apple")
        fetch_builtins.return_value = ({
            "apple": [{
                "key": "apple-1", "title": "Software Engineer",
                "location": "Cupertino, CA", "posted": today,
                "url": "https://example.test/apple-1",
            }]
        }, [])

        result = jobs_service.get_all_jobs(include_builtins=True)

        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["jobs"][0]["company"], "Apple")
        self.assertEqual(result["jobs"][0]["source"], "live-built-in")

    @patch("core.jobs_service.is_applied", return_value=False)
    @patch("core.jobs_service.list_companies", return_value=[])
    @patch("core.jobs_service.resume_store.active_resume_text", return_value="")
    @patch("core.jobs_service._fetch_custom_jobs")
    @patch("core.jobs_service.list_custom_companies")
    def test_removes_jobs_older_than_five_days(
        self, custom_companies, fetch_jobs, _resume, _builtins, _applied
    ):
        today = jobs_service._local_today()
        custom_companies.return_value = [
            {"name": "Example", "url": "https://example.test", "ats": "greenhouse", "token": "example"}
        ]
        common = {
            "title": "Software Engineer", "location": "Remote, US",
            "url": "https://example.test/job",
        }
        fetch_jobs.return_value = [
            {"key": "recent", "posted": (today - timedelta(days=5)).isoformat(), **common},
            {"key": "old", "posted": (today - timedelta(days=6)).isoformat(), **common},
        ]

        result = jobs_service.get_all_jobs(include_builtins=False)

        self.assertEqual([job["key"] for job in result["jobs"]], ["recent"])
        self.assertEqual(result["max_age_days"], 5)

    def test_undated_jobs_use_local_date_and_repair_future_discovery(self):
        raw_jobs = [(
            "Example", "example",
            {"key": "job-1", "title": "Software Engineer", "posted": ""},
            "live-built-in",
        )]
        with tempfile.TemporaryDirectory() as temp_dir:
            discovery_file = os.path.join(temp_dir, "discoveries.json")
            key = jobs_service._discovery_key("example", raw_jobs[0][2])
            with open(discovery_file, "w", encoding="utf-8") as handle:
                handle.write(f'{{"{key}": "2026-10-18"}}')

            with patch.object(jobs_service.config, "DASHBOARD_DISCOVERY_FILE", discovery_file), \
                    patch.object(jobs_service, "_local_today", return_value=date(2026, 10, 17)):
                result = jobs_service._assign_stable_dates(raw_jobs)

            self.assertEqual(result[0][2]["posted"], "")
            self.assertEqual(result[0][2]["discovered"], "2026-10-17")
            self.assertEqual(result[0][2]["sort_date"], "2026-10-17")
            self.assertEqual(result[0][2]["date_basis"], "first-seen")

    def test_parses_human_readable_source_date(self):
        self.assertEqual(
            jobs_service._parse_posted_date("October 17, 2026"),
            date(2026, 10, 17),
        )

    def test_extracts_only_labelled_posting_date_from_job_detail(self):
        self.assertEqual(
            jd_fetch.extract_posted_date(
                "Copyright 2026 Date Posted: October 12, 2026 Weekly Hours: 40"
            ),
            "2026-10-12",
        )
        self.assertEqual(jd_fetch.extract_posted_date("Copyright 2026"), "")

    @patch("core.jobs_service.config.get_company_runtime")
    def test_builtin_cache_with_missing_jd_is_refreshed(self, runtime):
        runtime.return_value = SimpleNamespace(included_role_keywords=("software engineer",))
        jobs = [{
            "title": "Software Engineer", "description": "", "url": "https://example.test/job"
        }]
        self.assertTrue(jobs_service._needs_description_refresh("example", jobs))

    @patch("core.jobs_service._save_builtin_cache")
    @patch("core.jobs_service.resume_store.active_resume_text", return_value="")
    @patch("core.jobs_service._fetch_one_description", new_callable=AsyncMock)
    @patch("core.jobs_service.config.get_company_runtime")
    @patch("core.jobs_service.list_companies", return_value=["apple"])
    def test_fetches_missing_builtin_jd_on_demand(
        self, _companies, runtime, fetch_description, _resume, _save_cache
    ):
        runtime.return_value = SimpleNamespace(display_name="Apple")
        fetch_description.return_value = "Build Python services on AWS. " * 4
        job = {
            "key": "apple-1", "title": "Software Engineer", "location": "Cupertino, CA",
            "posted": "2026-10-17", "description": "", "url": "https://example.test/job",
        }

        with patch.dict(jobs_service._BUILTIN_CACHE, {"apple": (0, [job])}, clear=True):
            result = jobs_service.get_builtin_job_details("apple", "apple-1")

        self.assertGreater(result["jd_chars"], 50)
        self.assertEqual(result["match_basis"], "full-description")
        fetch_description.assert_awaited_once_with("https://example.test/job")


if __name__ == "__main__":
    unittest.main()
