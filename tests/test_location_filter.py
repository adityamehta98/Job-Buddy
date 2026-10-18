import unittest

from location_filter import is_us_location


class UsLocationTests(unittest.TestCase):
    def test_accepts_state_qualified_locations(self):
        self.assertTrue(is_us_location("San Francisco, CA"))
        self.assertTrue(is_us_location("New York City, NY | Seattle, WA"))
        self.assertTrue(is_us_location("Austin, Texas"))

    def test_accepts_explicit_us_remote(self):
        self.assertTrue(is_us_location("Remote - US"))
        self.assertTrue(is_us_location("United States (Remote)"))

    def test_accepts_country_ambiguous_remote(self):
        self.assertTrue(is_us_location("Remote"))
        self.assertTrue(is_us_location("Remote-Friendly"))
        self.assertTrue(is_us_location("Work from anywhere"))

    def test_rejects_non_us_and_foreign_remote(self):
        self.assertFalse(is_us_location("London, UK"))
        self.assertFalse(is_us_location("Toronto, Canada"))
        self.assertFalse(is_us_location("Remote - UK"))
        self.assertFalse(is_us_location("Remote, Canada"))
        self.assertFalse(is_us_location("Remote - EMEA"))
        self.assertFalse(is_us_location("Multiple locations"))

    def test_remote_can_be_disabled(self):
        self.assertFalse(is_us_location("Remote", allow_remote=False))

    def test_keeps_multi_location_role_with_a_us_option(self):
        self.assertTrue(is_us_location("London, UK; San Francisco, CA"))


if __name__ == "__main__":
    unittest.main()
