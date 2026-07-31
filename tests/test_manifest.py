import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401
from sagctl import manifest as manifest_mod


class TestManifestValidate(unittest.TestCase):
    def _base(self, **overrides):
        m = {**manifest_mod.DEFAULTS, "source_id": "abc123", **overrides}
        return m

    def test_valid_minimal_passes(self):
        manifest_mod.validate(self._base())  # does not raise

    def test_missing_source_id_raises(self):
        m = self._base()
        del m["source_id"]
        with self.assertRaises(manifest_mod.ManifestError):
            manifest_mod.validate(m)

    def test_bad_key_format_raises(self):
        with self.assertRaises(manifest_mod.ManifestError):
            manifest_mod.validate(self._base(key_format="weird"))

    def test_bad_require_raises(self):
        with self.assertRaises(manifest_mod.ManifestError):
            manifest_mod.validate(self._base(require="whenever"))

    def test_confidence_out_of_range_raises(self):
        with self.assertRaises(manifest_mod.ManifestError):
            manifest_mod.validate(self._base(min_confidence=1.5))

    def test_duplicate_criteria_id_raises(self):
        m = self._base(criteria=[{"id": "c1", "text": "a"}, {"id": "c1", "text": "b"}])
        with self.assertRaises(manifest_mod.ManifestError):
            manifest_mod.validate(m)

    def test_criteria_missing_text_raises(self):
        m = self._base(criteria=[{"id": "c1"}])
        with self.assertRaises(manifest_mod.ManifestError):
            manifest_mod.validate(m)

    def test_negative_max_files_raises(self):
        with self.assertRaises(manifest_mod.ManifestError):
            manifest_mod.validate(self._base(max_files=0))


class TestManifestLoad(unittest.TestCase):
    def test_load_merges_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".sag-sync.json"
            p.write_text(json.dumps({"source_id": "abc"}), encoding="utf-8")
            m = manifest_mod.load(p)
            self.assertEqual(m["source_id"], "abc")
            self.assertEqual(m["key_format"], "flat")  # see selftest S1 on sag.home
            self.assertEqual(m["_repo_root"], str(p.parent))

    def test_load_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".sag-sync.json"
            p.write_text("{not json", encoding="utf-8")
            with self.assertRaises(manifest_mod.ManifestError):
                manifest_mod.load(p)

    def test_add_criterion_appends_and_rejects_dup(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".sag-sync.json"
            p.write_text(json.dumps({"source_id": "abc", "criteria": []}), encoding="utf-8")
            manifest_mod.add_criterion(p, "c1", "no meeting notes")
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(data["criteria"], [{"id": "c1", "text": "no meeting notes"}])
            with self.assertRaises(manifest_mod.ManifestError):
                manifest_mod.add_criterion(p, "c1", "dup")


if __name__ == "__main__":
    unittest.main()
