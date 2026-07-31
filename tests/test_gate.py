import unittest

import _bootstrap  # noqa: F401
from sagctl import gate
from sagctl import manifest as manifest_mod


def base_manifest(**overrides):
    return {**manifest_mod.DEFAULTS, "source_id": "abc", **overrides}


class TestCheckPathPolicy(unittest.TestCase):
    def test_included_passes(self):
        m = base_manifest(include=["docs/**/*.md"])
        r = gate.check_path_policy("docs/adr/x.md", m)
        self.assertTrue(r.ok)

    def test_not_included_fails(self):
        m = base_manifest(include=["docs/**/*.md"])
        r = gate.check_path_policy("src/x.py", m)
        self.assertFalse(r.ok)
        self.assertEqual(r.code, "NOT_INCLUDED")

    def test_excluded_fails_even_if_included(self):
        m = base_manifest(include=["**/*.md"], exclude=["docs/drafts/**"])
        r = gate.check_path_policy("docs/drafts/x.md", m)
        self.assertFalse(r.ok)
        self.assertEqual(r.code, "EXCLUDED_PATH")

    def test_deny_path_fails_with_specific_code(self):
        m = base_manifest(include=["**/*.md"], deny_paths=["docs/pricing/**"])
        r = gate.check_path_policy("docs/pricing/x.md", m)
        self.assertFalse(r.ok)
        self.assertEqual(r.code, "DENIED_PATH")


if __name__ == "__main__":
    unittest.main()
