import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_skill_sync.py"
SPEC = importlib.util.spec_from_file_location("check_skill_sync", SCRIPT)
assert SPEC and SPEC.loader
check_skill_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_skill_sync)


class SkillSyncTest(unittest.TestCase):
    def test_digest_is_stable_across_text_line_endings(self):
        self.assertEqual(
            check_skill_sync._digest_bytes(b"one\ntwo\n"),
            check_skill_sync._digest_bytes(b"one\r\ntwo\r\n"),
        )

    def test_hashes_detect_local_and_source_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "SKILL.md"
            source = root / "source.md"
            provenance = root / "PROVENANCE.md"
            skill.write_text("adapted\n")
            source.write_text("original\n")
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            provenance.write_text(
                f"- Source SHA-256: `{digest(source)}`\n"
                f"- Copy SHA-256: `{digest(skill)}`\n"
            )
            self.assertEqual(check_skill_sync.check(skill, provenance, source), [])
            self.assertEqual(check_skill_sync.check(skill, provenance, source_bytes=source.read_bytes()), [])
            source.write_text("new source\n")
            self.assertIn("source", " ".join(check_skill_sync.check(skill, provenance, source)))
            source.write_text("original\n")
            skill.write_text("edited copy\n")
            self.assertIn("copy", " ".join(check_skill_sync.check(skill, provenance, source)))


if __name__ == "__main__":
    unittest.main()
