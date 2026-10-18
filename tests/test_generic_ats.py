import unittest

from companies.generic_ats import _clean_html


class GenericAtsTests(unittest.TestCase):
    def test_cleans_regular_and_entity_encoded_html(self):
        self.assertEqual(_clean_html("<p>Hello <strong>world</strong></p>"), "Hello world")
        self.assertEqual(_clean_html("&lt;p&gt;Hello &lt;strong&gt;world&lt;/strong&gt;&lt;/p&gt;"), "Hello world")


if __name__ == "__main__":
    unittest.main()
