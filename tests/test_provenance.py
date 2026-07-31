import unittest

import _bootstrap  # noqa: F401
from sagctl import provenance


class TestProvenance(unittest.TestCase):
    def test_inject_creates_frontmatter_when_absent(self):
        out = provenance.inject("# Hello\n\nbody\n", {"sag_key": "docs/x.md"})
        self.assertTrue(out.startswith("---\nsag_key: docs/x.md\n---\n\n# Hello"))

    def test_inject_merges_into_existing_frontmatter(self):
        original = "---\ntitle: My Doc\nstatus: approved\n---\n\n# Hello\n"
        out = provenance.inject(original, {"sag_key": "docs/x.md", "sag_status": "published"})
        self.assertIn("title: My Doc", out)
        self.assertIn("status: approved", out)
        self.assertIn("sag_key: docs/x.md", out)
        self.assertIn("sag_status: published", out)
        # only ONE frontmatter block (exactly 2 consecutive '---' lines at the top, no second block created)
        self.assertEqual(out.count("---\n"), 2)

    def test_extract_frontmatter_field(self):
        out = provenance.inject("# Hello\n", {"sag_source_commit": "abcdef1"})
        val = provenance.extract_frontmatter_field(out, "sag_source_commit")
        self.assertEqual(val, "abcdef1")

    def test_extract_missing_field_returns_none(self):
        out = provenance.inject("# Hello\n", {"sag_key": "x"})
        self.assertIsNone(provenance.extract_frontmatter_field(out, "not_here"))

    def test_strip_for_comparison_removes_provenance_keys(self):
        original = "---\ntitle: My Doc\n---\n\nbody\n"
        injected = provenance.inject(original, {"sag_key": "docs/x.md", "sag_published_at": "2026-01-01"})
        stripped = provenance.strip_for_comparison(injected)
        self.assertNotIn("sag_key", stripped)
        self.assertNotIn("sag_published_at", stripped)
        self.assertIn("title: My Doc", stripped)

    def test_value_with_colon_is_quoted(self):
        out = provenance.inject("# H\n", {"sag_status": "note: draft"})
        self.assertIn('sag_status: "note: draft"', out)


if __name__ == "__main__":
    unittest.main()
