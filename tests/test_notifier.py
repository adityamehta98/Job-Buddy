import unittest
from unittest.mock import AsyncMock, patch

from core import notifier
class CompanyDigestTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_one_digest_with_every_job_link(self):
        jobs = [
            {
                "title": f"Software Engineer {index}",
                "location": "Remote, US",
                "url": f"https://jobs.example.com/roles/{index}?tracking=remove-me",
            }
            for index in range(1, 21)
        ]

        with patch.object(notifier, "_dispatch", new=AsyncMock(return_value=True)) as dispatch:
            delivered = await notifier.send_company_digest("Example Company", jobs)

        self.assertTrue(delivered)
        dispatch.assert_awaited_once()
        telegram, plain = dispatch.await_args.args[:2]
        self.assertEqual(dispatch.await_args.kwargs["telegram_parse_mode"], "HTML")
        self.assertIn("20 new roles in the last 24 hours", telegram)
        self.assertIn("20 new roles in the last 24 hours", plain)
        for index in range(1, 21):
            compact_url = f"https://jobs.example.com/roles/{index}"
            self.assertIn(compact_url, telegram)
            self.assertIn(compact_url, plain)
        self.assertNotIn("tracking=remove-me", telegram)
        self.assertNotIn("tracking=remove-me", plain)


if __name__ == "__main__":
    unittest.main()
