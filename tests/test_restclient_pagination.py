"""Regression test for list_documents_all — faithfully mocks the real SAG behavior
confirmed via selftest S6 on sag.home (2026-07-31): the server ignores limit/offset
entirely, always returning the ENTIRE list regardless of the parameters passed."""
import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401
from sagctl.restclient import SagClient


def make_docs(n):
    return [{"id": f"doc-{i}", "filename": f"doc-{i}.md"} for i in range(n)]


class TestListDocumentsAllIgnoresParams(unittest.TestCase):
    """Real SAG behavior: every call to list_documents (regardless of limit/offset)
    returns the same complete list, unchanged."""

    def _client_ignoring_params(self, total: int):
        client = SagClient(base_url="http://fake", token="t")
        docs = make_docs(total)

        def fake_list_documents(source_id, *, limit=None, offset=None):
            return docs  # always returns the full list, regardless of limit/offset

        client.list_documents = fake_list_documents
        return client

    def test_more_docs_than_page_size_not_flagged_truncated(self):
        # real case encountered: 120 documents, default page_size of 100
        client = self._client_ignoring_params(120)
        docs, truncated = client.list_documents_all("src", page_size=100)
        self.assertEqual(len(docs), 120)
        self.assertFalse(truncated)

    def test_exactly_page_size_not_flagged_truncated(self):
        client = self._client_ignoring_params(100)
        docs, truncated = client.list_documents_all("src", page_size=100)
        self.assertEqual(len(docs), 100)
        self.assertFalse(truncated)

    def test_fewer_than_page_size_not_flagged_truncated(self):
        client = self._client_ignoring_params(5)
        docs, truncated = client.list_documents_all("src", page_size=100)
        self.assertEqual(len(docs), 5)
        self.assertFalse(truncated)


class TestListDocumentsAllRealPagination(unittest.TestCase):
    """HYPOTHETICAL case where the server actually honors offset (not yet seen on
    real SAG, but the code must handle it correctly if a later version adds real pagination)."""

    def _client_real_pagination(self, total: int, page_size: int = 10):
        client = SagClient(base_url="http://fake", token="t")
        docs = make_docs(total)

        def fake_list_documents(source_id, *, limit=None, offset=None):
            offset = offset or 0
            limit = limit or len(docs)
            return docs[offset : offset + limit]

        client.list_documents = fake_list_documents
        return client

    def test_accumulates_across_real_pages(self):
        client = self._client_real_pagination(25, page_size=10)
        docs, truncated = client.list_documents_all("src", page_size=10)
        self.assertEqual(len(docs), 25)
        self.assertFalse(truncated)
        self.assertEqual({d["id"] for d in docs}, {f"doc-{i}" for i in range(25)})

    def test_exact_multiple_of_page_size(self):
        client = self._client_real_pagination(20, page_size=10)
        docs, truncated = client.list_documents_all("src", page_size=10)
        self.assertEqual(len(docs), 20)
        self.assertFalse(truncated)


if __name__ == "__main__":
    unittest.main()
