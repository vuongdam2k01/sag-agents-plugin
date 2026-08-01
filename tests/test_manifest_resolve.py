"""manifest.resolve() / git_root() (SPEC A3).

The property under test: a manifest, and the document it governs, no longer have to
sit inside a Git repository. Git becomes one source of provenance among several, not
the gate in front of publishing.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from sagctl import manifest as manifest_mod


def _write_manifest(path: Path, **overrides) -> Path:
    doc = {"source_id": "src-x", **overrides}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


class TestGitOptional(unittest.TestCase):
    def test_git_root_is_none_outside_any_repo(self):
        with tempfile.TemporaryDirectory() as td:
            m = manifest_mod.load(_write_manifest(Path(td) / ".sag-sync.json"))
            self.assertIsNone(manifest_mod.git_root(m))

    def test_git_root_finds_a_real_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            m = manifest_mod.load(_write_manifest(root / ".sag-sync.json"))
            self.assertEqual(manifest_mod.git_root(m), root.resolve())

    def test_find_manifest_does_not_require_a_repo(self):
        """A .sag-sync.json above a file is enough — no git init anywhere in the
        ancestor chain. This is what lets a Hermes working directory publish."""
        with tempfile.TemporaryDirectory() as td:
            # .resolve() up front: find_manifest() resolves internally, and on a
            # Windows CI runner (account name "runneradmin") the raw tempdir path
            # carries an 8.3 short-name component that only expands under
            # .resolve() — comparing resolved-vs-unresolved fails there even
            # though the paths are the same directory.
            root = Path(td).resolve()
            _write_manifest(root / ".sag-sync.json")
            sub = root / "research"
            sub.mkdir()
            found = manifest_mod.find_manifest(sub)
            self.assertEqual(found, root / ".sag-sync.json")

    def test_require_no_longer_accepts_none(self):
        """require: "none" was the half-built version of this — Mode A pretending to
        be Mode B. Superseded by git_root() being allowed to return None outright."""
        with self.assertRaises(manifest_mod.ManifestError):
            manifest_mod.validate({**manifest_mod.DEFAULTS, "source_id": "s", "require": "none"})

    def test_canonical_branch_required_only_for_pushed_or_merged(self):
        base = {**manifest_mod.DEFAULTS, "source_id": "s", "require": "committed"}
        del base["canonical_branch"]
        manifest_mod.validate(base)  # does not raise — committed does not need it

        pushed = {**base, "require": "pushed"}
        with self.assertRaises(manifest_mod.ManifestError):
            manifest_mod.validate(pushed)

    def test_include_default_is_every_extension_not_just_markdown(self):
        """The old default (**/*.md) was a consequence of provenance being welded to
        YAML frontmatter, never a judgement that only markdown can be knowledge —
        provenance for other formats now lives in the state store."""
        self.assertEqual(manifest_mod.DEFAULTS["include"], ["**/*"])

    def test_every_include_fallback_agrees_with_the_default(self):
        """gate.py, routing.py, and sync.py each fall back to *something* when a
        manifest sets `include: []` explicitly. Before this fix they were three
        independent literals (sync.py's was still **/*.md) — an empty `include`
        would make sync's file discovery and the publish floor disagree about what
        "everything" means. All three must reference manifest.DEFAULTS now."""
        from sagctl import gate, routing, sync

        m = {**manifest_mod.DEFAULTS, "source_id": "s", "include": []}
        self.assertTrue(gate.check_path_policy("anything.pdf", m).ok)
        self.assertTrue(routing._included("anything.pdf", m))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "x.pdf").write_bytes(b"\x00\x01")
            candidates = sync._list_candidate_files(root, m)
        self.assertTrue(any(p.name == "x.pdf" for p in candidates))


class TestResolve(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SAGCTL_HOME"] = self._tmp.name
        os.environ.pop(manifest_mod.ENV_MANIFEST, None)

    def tearDown(self):
        os.environ.pop("SAGCTL_HOME", None)
        os.environ.pop(manifest_mod.ENV_MANIFEST, None)
        self._tmp.cleanup()

    def test_explicit_path_wins_over_everything(self):
        with tempfile.TemporaryDirectory() as td:
            explicit = _write_manifest(Path(td) / "explicit.json", source_id="explicit")
            os.environ[manifest_mod.ENV_MANIFEST] = str(_write_manifest(Path(td) / "env.json", source_id="env"))
            m = manifest_mod.resolve(explicit=explicit)
            self.assertEqual(m["source_id"], "explicit")

    def test_named_manifest_wins_over_env(self):
        named_path = manifest_mod.named_manifest("hermes-research")
        named_path.parent.mkdir(parents=True, exist_ok=True)
        _write_manifest(named_path, source_id="named")
        with tempfile.TemporaryDirectory() as td:
            os.environ[manifest_mod.ENV_MANIFEST] = str(_write_manifest(Path(td) / "env.json", source_id="env"))
            m = manifest_mod.resolve(name="hermes-research")
            self.assertEqual(m["source_id"], "named")

    def test_env_var_wins_over_walking_up_from_start(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_manifest(root / ".sag-sync.json", source_id="from-walk")
            os.environ[manifest_mod.ENV_MANIFEST] = str(_write_manifest(root / "env.json", source_id="from-env"))
            m = manifest_mod.resolve(root)
            self.assertEqual(m["source_id"], "from-env")

    def test_falls_back_to_walking_up_from_start(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_manifest(root / ".sag-sync.json", source_id="from-walk")
            sub = root / "a" / "b"
            sub.mkdir(parents=True)
            m = manifest_mod.resolve(sub)
            self.assertEqual(m["source_id"], "from-walk")

    def test_no_manifest_anywhere_raises_a_clear_error(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(manifest_mod.ManifestError) as ctx:
                manifest_mod.resolve(Path(td))
            msg = str(ctx.exception)
            self.assertIn("--manifest", msg)
            self.assertIn(manifest_mod.ENV_MANIFEST, msg)

    def test_named_manifest_missing_raises(self):
        with self.assertRaises(manifest_mod.ManifestError):
            manifest_mod.resolve(name="does-not-exist")

    def test_load_for_is_resolve_with_a_start_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_manifest(root / ".sag-sync.json", source_id="via-load-for")
            m = manifest_mod.load_for(root / "some" / "file.md")
            self.assertEqual(m["source_id"], "via-load-for")


if __name__ == "__main__":
    unittest.main()
