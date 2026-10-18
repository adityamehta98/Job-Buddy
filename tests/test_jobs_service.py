import unittest
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


if __name__ == "__main__":
    unittest.main()
