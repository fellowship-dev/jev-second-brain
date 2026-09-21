from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from jev_second_brain.index import get_note, list_notes, scan_and_index, search


FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "synthetic-vault"


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.db = self.root / "index.sqlite"

    def put(self, path: str, content: str):
        source = self.vault / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content, encoding="utf-8")

    def test_first_scan_search_and_unchanged_replay(self):
        for source in FIXTURE.rglob("*.md"):
            self.put(source.relative_to(FIXTURE).as_posix(), source.read_text())
        report = scan_and_index(self.vault, self.db)
        self.assertEqual(report.total, 5)
        self.assertEqual(report.added, 5)
        self.assertEqual(scan_and_index(self.vault, self.db).unchanged, 5)
        paths = [hit.path for hit in search(self.db, "onboarding", limit=10)]
        self.assertIn("projects/aurora-checklist.md", paths)
        self.assertNotIn("personal/garden.md", paths)
        self.assertEqual(search(self.db, "???"), [])
        self.assertTrue(search(self.db, 'launch:"(onboarding)'))

    def test_edit_rename_and_tombstone(self):
        self.put("a.md", "# New idea\n\nFirst version.")
        scan_and_index(self.vault, self.db)
        original = list_notes(self.db)[0]
        self.put("a.md", "# New idea\n\nSecond version.")
        changed = scan_and_index(self.vault, self.db)
        self.assertEqual(changed.changed, 1)
        self.assertEqual(list_notes(self.db)[0].id, original.id)
        (self.vault / "a.md").rename(self.vault / "moved.md")
        renamed = scan_and_index(self.vault, self.db)
        self.assertEqual(renamed.renamed, 1)
        self.assertEqual(list_notes(self.db)[0].id, original.id)
        (self.vault / "moved.md").unlink()
        removed = scan_and_index(self.vault, self.db)
        self.assertEqual(removed.tombstoned, 1)
        self.assertEqual(list_notes(self.db), [])
        self.assertIsNone(get_note(self.db, original.id))
        self.assertEqual(len(list_notes(self.db, include_deleted=True)), 1)
        self.assertEqual(search(self.db, "version"), [])
        self.put("moved.md", "# Other\n\nThird version.")
        self.assertEqual(scan_and_index(self.vault, self.db).added, 1)
        self.assertEqual(len(list_notes(self.db, include_deleted=True)), 2)

    def test_failed_scan_preserves_active_index(self):
        self.put("good.md", "# Good\n")
        scan_and_index(self.vault, self.db)
        (self.vault / "good.md").unlink()
        (self.vault / "bad.md").write_bytes(b"\xff")
        with self.assertRaises(UnicodeDecodeError):
            scan_and_index(self.vault, self.db)
        self.assertEqual([note.path for note in list_notes(self.db)], ["good.md"])

    def test_ambiguous_content_rename_does_not_reuse_id(self):
        self.put("a.md", "same")
        self.put("b.md", "same")
        scan_and_index(self.vault, self.db)
        originals = {note.id for note in list_notes(self.db)}
        (self.vault / "a.md").rename(self.vault / "c.md")
        (self.vault / "b.md").rename(self.vault / "d.md")
        report = scan_and_index(self.vault, self.db)
        self.assertEqual(report.renamed, 0)
        self.assertEqual(report.added, 2)
        self.assertEqual(report.tombstoned, 2)
        self.assertTrue(originals.isdisjoint({note.id for note in list_notes(self.db)}))

    def test_index_is_bound_to_one_vault(self):
        self.put("a.md", "# A")
        scan_and_index(self.vault, self.db)
        second = self.root / "second"
        second.mkdir()
        with self.assertRaises(ValueError):
            scan_and_index(second, self.db)
        self.assertEqual(len(list_notes(self.db)), 1)


if __name__ == "__main__":
    unittest.main()
