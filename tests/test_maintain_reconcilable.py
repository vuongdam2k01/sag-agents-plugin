"""maintain._reconcilable() (SPEC A3) — orphan/stale-branch detection must not
reconcile a document that was never a path in the repo to begin with. Getting this
wrong is how a real authored document gets proposed for deletion: `path_exists_at_ref`
is always False for a key that was never a real repo path.
"""
import os
import tempfile
import unittest

import _bootstrap  # noqa: F401

from sagctl import maintain, state


class TestReconcilable(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SAGCTL_HOME"] = self._tmp.name
        state.reset_backend()

    def tearDown(self):
        state.reset_backend()
        os.environ.pop("SAGCTL_HOME", None)
        self._tmp.cleanup()

    def test_no_provenance_record_defaults_to_reconcilable(self):
        """Predates A1/A3 — treated as reconcilable, matching engine behavior before
        this distinction existed."""
        self.assertTrue(maintain._reconcilable("src-a", "docs__x.md"))

    def test_file_in_git_is_reconcilable(self):
        state.provenance_put("src-a", "docs__x.md", {"sag_in_git": True})
        self.assertTrue(maintain._reconcilable("src-a", "docs__x.md"))

    def test_authored_document_is_not_reconcilable(self):
        state.provenance_put("src-a", "research__notes.md", {"sag_in_git": False, "sag_authored": True})
        self.assertFalse(maintain._reconcilable("src-a", "research__notes.md"))

    def test_missing_sag_in_git_field_defaults_true(self):
        """A record with no sag_in_git key at all (e.g. hand-written) must not be
        silently treated as unreconcilable."""
        state.provenance_put("src-a", "docs__x.md", {"sag_key": "docs__x.md"})
        self.assertTrue(maintain._reconcilable("src-a", "docs__x.md"))

    def test_isolated_per_source(self):
        state.provenance_put("src-a", "k.md", {"sag_in_git": False})
        self.assertTrue(maintain._reconcilable("src-b", "k.md"))


if __name__ == "__main__":
    unittest.main()
