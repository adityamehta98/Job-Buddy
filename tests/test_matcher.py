import unittest

import matcher


class MatcherTests(unittest.TestCase):
    def test_returns_transparent_per_keyword_evidence(self):
        result = matcher.score(
            "Built Python services on AWS with Docker.",
            "We need Python, SQL, AWS, and Kubernetes experience.",
        )

        self.assertEqual(result["match"], 50)
        self.assertEqual(result["matched"], ["aws", "python"])
        self.assertEqual(result["missing"], ["kubernetes", "sql"])
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual(result["jd_skill_count"], 4)
        details = {row["keyword"]: row for row in result["keyword_details"]}
        self.assertIn("Python", details["python"]["jd_evidence"])
        self.assertIn("Python", details["python"]["resume_evidence"])
        self.assertEqual(details["sql"]["resume_evidence"], "")

    def test_does_not_report_vacuous_one_hundred_percent(self):
        result = matcher.score("Experienced engineer", "Friendly collaborative team")
        self.assertIsNone(result["match"])
        self.assertEqual(result["jd_skill_count"], 0)

    def test_extracts_jd_keywords_without_a_resume(self):
        result = matcher.analyze_jd("Build Python APIs on AWS and Kubernetes.")
        self.assertIsNone(result["match"])
        self.assertEqual(result["extracted"], ["aws", "kubernetes", "python"])
        self.assertTrue(all(row["matched"] is None for row in result["keyword_details"]))


if __name__ == "__main__":
    unittest.main()
