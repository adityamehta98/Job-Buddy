import json
import threading
import unittest

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from app import app


class DashboardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server("127.0.0.1", 0, app)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def test_search_sort_and_twenty_row_pagination(self):
        jobs = []
        for index in range(25):
            jobs.append({
                "company": "Beta" if index % 2 else "Alpha",
                "slug": "beta" if index % 2 else "alpha",
                "key": f"job-{index}",
                "title": f"Software Engineer {index:02d}",
                "team": "Platform",
                "location": "Remote, US",
                "posted": f"2026-10-{17 - (index % 5):02d}",
                "date_basis": "posted",
                "url": f"https://example.test/{index}",
                "description": "",
                "applied": False,
                "source": "test",
                "match": index,
                "missing": ["python"],
                "keyword_details": [],
                "matched_count": 0,
                "jd_skill_count": 1,
            })
        payload = {
            "jobs": jobs, "errors": [], "has_cv": True,
            "us_only": True, "filtered_non_us": 3, "max_age_days": 5,
        }

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.route(
                "**/api/jobs**",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(payload),
                ),
            )
            page.goto(f"http://127.0.0.1:{self.port}")
            page.wait_for_function("document.querySelectorAll('#jobsTable tbody tr').length === 20")

            self.assertEqual(page.locator("#jobsTable tbody tr").count(), 20)
            self.assertIn("Page 1 of 2", page.locator("#pageStatus").inner_text())

            page.locator("#nextPage").click()
            self.assertEqual(page.locator("#jobsTable tbody tr").count(), 5)

            page.locator("#jobSearch").fill("Engineer 24")
            self.assertEqual(page.locator("#jobsTable tbody tr").count(), 1)
            self.assertIn("Software Engineer 24", page.locator("#jobsTable tbody").inner_text())

            page.locator("#jobSearch").fill("")
            page.locator("#companyFilter").select_option("Beta")
            self.assertEqual(page.locator("#jobsTable tbody tr").count(), 12)

            page.locator("#companyFilter").select_option("")
            page.locator("#dateFilter").select_option("2026-10-17")
            self.assertEqual(page.locator("#jobsTable tbody tr").count(), 5)

            page.locator("#dateFilter").select_option("")
            page.locator("#jobSort").select_option("role-asc")
            first_title = page.locator("#jobsTable tbody tr").first.locator("td").nth(1).inner_text()
            self.assertIn("Software Engineer 00", first_title)
            browser.close()


if __name__ == "__main__":
    unittest.main()
