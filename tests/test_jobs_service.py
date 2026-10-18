import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jobs_service


class JobsServiceTests(unittest.TestCase):
    @patch("jobs_service.is_applied", return_value=False)
    @patch("jobs_service.list_companies", return_value=[])
    @patch("jobs_service.resume_store.active_resume_text", return_value="Python and AWS")
    @patch("jobs_service._fetch_custom_jobs")
    @patch("jobs_service.list_custom_companies")
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

    @patch("jobs_service.is_applied", return_value=False)
    @patch("jobs_service.resume_store.active_resume_text", return_value="")
    @patch("jobs_service.list_custom_companies", return_value=[])
    @patch("jobs_service.list_companies", return_value=["apple"])
    @patch("jobs_service._fetch_builtin_jobs")
    @patch("jobs_service.config.get_company_runtime")
    def test_fetches_builtin_companies_live(
        self, runtime, fetch_builtins, _companies, _custom, _resume, _applied
    ):
        today = datetime.now(timezone.utc).date().isoformat()
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

    @patch("jobs_service.is_applied", return_value=False)
    @patch("jobs_service.list_companies", return_value=[])
    @patch("jobs_service.resume_store.active_resume_text", return_value="")
    @patch("jobs_service._fetch_custom_jobs")
    @patch("jobs_service.list_custom_companies")
    def test_removes_jobs_older_than_five_days(
        self, custom_companies, fetch_jobs, _resume, _builtins, _applied
    ):
        today = datetime.now(timezone.utc).date()
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


if __name__ == "__main__":
    unittest.main()
