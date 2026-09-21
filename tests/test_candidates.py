from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jev_second_brain.candidates import candidates_for_note
from jev_second_brain.index import list_notes, scan_and_index


class CandidateTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.db = self.root / "index.sqlite"

    def put(self, name: str, content: str):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_link_directions_and_reasons(self):
        self.put("projects/aurora.md", "# Aurora launch\nSee [[projects/checklist]].")
        self.put("projects/checklist.md", "# Checklist\nReview Aurora onboarding.")
        self.put("meetings/review.md", '# Review\nSee [launch](../projects/aurora.md).')
        self.put("garden.md", "# Garden\nPlant seeds.")
        scan_and_index(self.vault, self.db)
        notes = {note.path: note for note in list_notes(self.db)}
        batch = candidates_for_note(self.db, notes["projects/aurora.md"].id, k=2)
        self.assertEqual(batch.eligible_count, 3)
        self.assertEqual(batch.returned_count, 2)
        self.assertEqual(batch.candidates[0].path, "projects/checklist.md")
        self.assertIn("outgoing_link", batch.candidates[0].reasons)
        review = next(candidate for candidate in batch.candidates if candidate.path == "meetings/review.md")
        self.assertIn("incoming_link", review.reasons)
        self.assertEqual(batch.pool_count, batch.returned_count + batch.truncated_count)

    def test_duplicate_hash_title_overlap_and_cap(self):
        self.put("a.md", "# Aurora launch\nUpdate")
        self.put("b.md", "# Aurora launch\nUpdate")
        self.put("c.md", "# Aurora delivery\nUpdate")
        self.put("d.md", "# Garden\nUnrelated")
        scan_and_index(self.vault, self.db)
        notes = {note.path: note for note in list_notes(self.db)}
        batch = candidates_for_note(self.db, notes["a.md"].id, k=1)
        self.assertEqual(batch.returned_count, 1)
        self.assertGreater(batch.truncated_count, 0)
        self.assertEqual(batch.candidates[0].path, "b.md")
        self.assertIn("same_content", batch.candidates[0].reasons)
        wider = candidates_for_note(self.db, notes["a.md"].id, k=3)
        self.assertIn("title_overlap", next(c for c in wider.candidates if c.path == "c.md").reasons)

    def test_substantial_body_overlap_beats_shared_title_words(self):
        self.put(
            "source.md",
            "# Falcon readiness conversation\n"
            "Release a small canary group, inspect telemetry, and expand only after error indicators stay quiet.",
        )
        self.put(
            "related.md",
            "# Progressive rollout method\n"
            "Begin with a small canary group. Inspect telemetry before expanding while error indicators remain quiet.",
        )
        self.put(
            "unrelated.md",
            "# Falcon garden conversation\n"
            "A falcon visited the garden while neighbors discussed quiet weekend plans.",
        )
        scan_and_index(self.vault, self.db)
        notes = {note.path: note for note in list_notes(self.db)}
        batch = candidates_for_note(self.db, notes["source.md"].id, k=3)
        self.assertEqual(batch.candidates[0].path, "related.md")
        self.assertIn("lexical_overlap", batch.candidates[0].reasons)
        self.assertNotIn("unrelated.md", [candidate.path for candidate in batch.candidates])

    def test_missing_id_and_invalid_cap(self):
        self.put("a.md", "# A")
        scan_and_index(self.vault, self.db)
        with self.assertRaises(ValueError):
            candidates_for_note(self.db, "missing")
        with self.assertRaises(ValueError):
            candidates_for_note(self.db, list_notes(self.db)[0].id, k=0)

    def test_shared_body_terms_can_find_different_titles(self):
        self.put("field-note.md", "# Field note\nThe blue telescope observes distant stars.")
        self.put("optics.md", "# Optics\nTelescope mirrors focus distant stars.")
        self.put("garden.md", "# Garden\nTomato seeds sprout.")
        scan_and_index(self.vault, self.db)
        notes = {note.path: note for note in list_notes(self.db)}
        batch = candidates_for_note(self.db, notes["field-note.md"].id, k=2)
        self.assertIn("optics.md", [candidate.path for candidate in batch.candidates])


if __name__ == "__main__":
    unittest.main()
