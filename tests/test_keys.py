import unittest

import _bootstrap  # noqa: F401
from sagctl import keys


class TestKeys(unittest.TestCase):
    def test_encode_path_format(self):
        self.assertEqual(keys.encode_key("docs/adr/x.md", "path"), "docs/adr/x.md")

    def test_encode_normalizes_backslash(self):
        self.assertEqual(keys.encode_key("docs\\adr\\x.md", "path"), "docs/adr/x.md")

    def test_encode_flat_format(self):
        self.assertEqual(keys.encode_key("docs/adr/x.md", "flat"), "docs__adr__x.md")

    def test_flat_rejects_double_underscore(self):
        with self.assertRaises(keys.KeyFormatError):
            keys.encode_key("docs/a__b/x.md", "flat")

    def test_decode_flat_roundtrip(self):
        encoded = keys.encode_key("docs/adr/x.md", "flat")
        self.assertEqual(keys.decode_key(encoded, "flat"), "docs/adr/x.md")

    def test_decode_path_is_identity(self):
        self.assertEqual(keys.decode_key("docs/adr/x.md", "path"), "docs/adr/x.md")

    def test_unknown_format_raises(self):
        with self.assertRaises(keys.KeyFormatError):
            keys.encode_key("x.md", "bogus")

    def test_assert_no_drift_passes_when_equal(self):
        keys.assert_no_drift("docs/x.md", "docs/x.md")  # does not raise

    def test_assert_no_drift_raises_when_different(self):
        with self.assertRaises(keys.KeyFormatDriftError):
            keys.assert_no_drift("docs/x.md", "x.md")

    def test_leading_slash_stripped(self):
        self.assertEqual(keys.encode_key("/docs/x.md", "path"), "docs/x.md")


if __name__ == "__main__":
    unittest.main()
