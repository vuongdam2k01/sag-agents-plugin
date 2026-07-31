import unittest

import _bootstrap  # noqa: F401
from sagctl import globmatch


class TestGlobMatch(unittest.TestCase):
    def test_double_star_matches_zero_directories(self):
        self.assertTrue(globmatch.match("docs/x.md", "docs/**/*.md"))

    def test_double_star_matches_one_directory(self):
        self.assertTrue(globmatch.match("docs/adr/x.md", "docs/**/*.md"))

    def test_double_star_matches_many_directories(self):
        self.assertTrue(globmatch.match("docs/a/b/c/x.md", "docs/**/*.md"))

    def test_no_match_wrong_prefix(self):
        self.assertFalse(globmatch.match("src/x.py", "docs/**/*.md"))

    def test_exact_match_no_wildcard(self):
        self.assertTrue(globmatch.match("docs/x.md", "docs/x.md"))
        self.assertFalse(globmatch.match("docs/y.md", "docs/x.md"))

    def test_trailing_double_star_matches_everything_under(self):
        self.assertTrue(globmatch.match("docs/drafts/x.md", "docs/drafts/**"))
        self.assertTrue(globmatch.match("docs/drafts/a/b.md", "docs/drafts/**"))
        self.assertFalse(globmatch.match("docs/other/x.md", "docs/drafts/**"))

    def test_single_star_does_not_cross_slash(self):
        self.assertFalse(globmatch.match("docs/adr/x.md", "docs/*.md"))
        self.assertTrue(globmatch.match("docs/x.md", "docs/*.md"))

    def test_match_any(self):
        self.assertTrue(globmatch.match_any("docs/x.md", ["src/**", "docs/**/*.md"]))
        self.assertFalse(globmatch.match_any("docs/x.md", ["src/**", "other/**"]))

    def test_this_regression_case_from_manual_testing(self):
        # discovered during manual testing: fnmatch.fnmatch incorrectly returns False
        # for this case — globmatch must return True.
        self.assertTrue(globmatch.match("docs/normal.md", "docs/**/*.md"))


if __name__ == "__main__":
    unittest.main()
