"""Document key encoding (SPEC S2).

key = a document's durable identifier in SAG, used for dedup and as a citation:
`source + key(+heading)`. Different from `document_id`/`chunk_id` — those change
every time content changes (SAG has no update API), so they must NOT be used as
a long-lived citation.

`key_format` is locked in ONCE at source provisioning time (written into the
manifest) and never changes afterward — REVIEW-OPUS C2/F10: changing the format
mid-stream produces two different keys for the same file over time, dedup will
slip, and duplicates get created permanently.
"""
from __future__ import annotations

FLAT_SEPARATOR = "__"


class KeyFormatError(RuntimeError):
    pass


class KeyFormatDriftError(RuntimeError):
    """SAG returned a filename different from the key that was sent — the
    key_format assumption is no longer valid.

    This is a mandatory ASSERTION after EVERY upload (REVIEW-OPUS C2-L1): the
    key_format decision made at provisioning time is only a snapshot of SAG's
    behavior at that moment; if SAG changes how it handles filenames in a later
    version, this must be detected immediately and halt, rather than silently
    deduping incorrectly and deleting the wrong document.
    """

    def __init__(self, expected: str, actual: str):
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"KEY_FORMAT_DRIFT: sent key='{expected}' but SAG returned filename='{actual}'. "
            f"The key_format assumption in the manifest is no longer valid — STOP, do not write the lock, "
            f"re-verify with `sagctl selftest --case filename-roundtrip`."
        )


def to_posix(relpath: str) -> str:
    return relpath.replace("\\", "/")


def encode_key(relpath: str, key_format: str) -> str:
    rel = to_posix(relpath).lstrip("/")
    if key_format == "path":
        return rel
    if key_format == "flat":
        if FLAT_SEPARATOR in rel:
            raise KeyFormatError(
                f"relpath contains the reserved separator string '{FLAT_SEPARATOR}': {rel} — "
                f"rename the file/directory to not contain '{FLAT_SEPARATOR}' (keeps the encoding bijective)."
            )
        return rel.replace("/", FLAT_SEPARATOR)
    raise KeyFormatError(f"invalid key_format: {key_format}")


def decode_key(key: str, key_format: str) -> str:
    if key_format == "path":
        return key
    if key_format == "flat":
        return key.replace(FLAT_SEPARATOR, "/")
    raise KeyFormatError(f"invalid key_format: {key_format}")


def assert_no_drift(expected_key: str, returned_filename: str) -> None:
    if returned_filename != expected_key:
        raise KeyFormatDriftError(expected_key, returned_filename)
