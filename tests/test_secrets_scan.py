import unittest

import _bootstrap  # noqa: F401
from sagctl import secrets_scan


class TestSecretsScan(unittest.TestCase):
    def test_aws_access_key_detected(self):
        findings = secrets_scan.scan_text("key = AKIAABCDEFGHIJKLMNOP\n")
        self.assertTrue(any(f.kind == "aws_access_key_id" for f in findings))

    def test_github_token_detected(self):
        findings = secrets_scan.scan_text("token: ghp_" + "a" * 40)
        self.assertTrue(any(f.kind == "github_token" for f in findings))

    def test_private_key_block_detected(self):
        findings = secrets_scan.scan_text("-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----")
        self.assertTrue(any(f.kind == "private_key_block" for f in findings))

    def test_clean_text_no_findings_from_patterns(self):
        findings = secrets_scan.scan_text("# ADR\n\nThis is a normal document with no secrets.\n")
        pattern_findings = [f for f in findings if f.kind != "high_entropy_token"]
        self.assertEqual(pattern_findings, [])

    def test_redaction_does_not_leak_full_secret(self):
        findings = secrets_scan.scan_text("key = AKIAABCDEFGHIJKLMNOP\n")
        for f in findings:
            self.assertNotIn("AKIAABCDEFGHIJKLMNOP", f.snippet)


if __name__ == "__main__":
    unittest.main()
