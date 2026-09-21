from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jev_second_brain.alignment import MAX_CANDIDATES, suggest_for_note
from jev_second_brain.index import list_notes, scan_and_index
from jev_second_brain.provider import EvaluationResult, MODEL
from decimal import Decimal


@dataclass
class FakeProvider:
    relation: str = "related"
    failure_after: int | None = None
    strength: float = .9

    def __post_init__(self):
        self.calls: list[tuple[dict, dict, bool]] = []

    def evaluate(self, state, questions, *, private=True):
        self.calls.append((state, questions, private))
        if self.failure_after is not None and len(self.calls) > self.failure_after:
            raise RuntimeError("synthetic provider failure")
        labels = tuple(questions["relation"]["criteria"])
        probabilities = {label: (1 - self.strength) / (len(labels) - 1) for label in labels}
        probabilities[self.relation] = self.strength
        return EvaluationResult(
            model=MODEL,
            answers={"relation": {"type": "choice", "choice": self.relation,
                                   "probabilities": probabilities}},
            input_tokens=30, output_tokens=3, cost_usd=Decimal("0.00001"),
            routing={"finalProvider": "typesafe-ai"}, generation_id=f"fake-{len(self.calls)}",
        )


class AlignmentTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.db = self.root / "index.sqlite"
        self.cache = self.root / "alignment.sqlite"

    def put(self, name: str, text: str):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def indexed(self, path="a.md") -> str:
        scan_and_index(self.vault, self.db)
        return {note.path: note.id for note in list_notes(self.db)}[path]

    def test_local_shortlist_has_no_provider_calls_or_cache_write(self):
        self.put("a.md", "# Aurora launch\nSee [[b]].")
        self.put("b.md", "# Aurora checklist\nThe launch checklist.")
        source = self.indexed()
        provider = FakeProvider()
        result = suggest_for_note(self.db, source, provider=provider, cache_path=self.cache)
        self.assertEqual(result.candidates.returned_count, 1)
        self.assertEqual(result.candidates.candidates[0].path, "b.md")
        self.assertEqual(result.judgments, ())
        self.assertEqual(result.provider_calls, 0)
        self.assertEqual(result.pending_count, 1)
        self.assertEqual(provider.calls, [])
        self.assertFalse(self.cache.exists())

    def test_bounded_evaluation_and_unchanged_replay(self):
        self.put("a.md", "# Aurora launch\nSee [[b]], [[c]], [[d]].")
        for name in ("b", "c", "d"):
            self.put(f"{name}.md", f"# Aurora {name}\nRelevant launch details.")
        source = self.indexed()
        provider = FakeProvider()
        first = suggest_for_note(self.db, source, k=2, provider=provider,
                                 cache_path=self.cache, evaluate=True)
        self.assertEqual(first.candidates.returned_count, 2)
        self.assertGreater(first.candidates.truncated_count, 0)
        self.assertEqual(first.provider_calls, 2)
        self.assertEqual(first.pending_count, 2)
        self.assertEqual(len(first.judgments), 2)
        self.assertTrue(all(j.relation == "related" and j.proposal_id for j in first.judgments))
        self.assertTrue(all(j.source_path == "a.md" for j in first.judgments))
        self.assertEqual({call[2] for call in provider.calls}, {True})
        self.assertEqual(provider.calls[0][0]["source_path"], "a.md")
        self.assertIn("source_text", provider.calls[0][0])
        replay = suggest_for_note(self.db, source, k=2, provider=provider,
                                  cache_path=self.cache, evaluate=True)
        self.assertEqual(replay.provider_calls, 0)
        self.assertEqual(replay.cache_hits, 2)
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(all(j.from_cache for j in replay.judgments))
        self.assertEqual(replay.pending_count, 0)
        preview = suggest_for_note(self.db, source, k=2, cache_path=self.cache)
        self.assertEqual(preview.pending_count, 0)
        self.assertEqual(preview.cache_hits, 2)
        self.assertEqual(preview.provider_calls, 0)

    def test_only_edited_pair_is_rejudged(self):
        self.put("a.md", "# Aurora launch\nSee [[b]], [[c]].")
        self.put("b.md", "# Aurora b\nOld detail")
        self.put("c.md", "# Aurora c\nStable detail")
        source = self.indexed()
        provider = FakeProvider()
        first = suggest_for_note(self.db, source, provider=provider,
                                 cache_path=self.cache, evaluate=True)
        old_ids = {j.target_path: j.proposal_id for j in first.judgments}
        self.put("b.md", "# Aurora b\nChanged detail")
        self.indexed()
        second = suggest_for_note(self.db, source, provider=provider,
                                  cache_path=self.cache, evaluate=True)
        self.assertEqual(second.provider_calls, 1)
        self.assertEqual(second.cache_hits, 1)
        new_ids = {j.target_path: j.proposal_id for j in second.judgments}
        self.assertNotEqual(old_ids["b.md"], new_ids["b.md"])
        self.assertEqual(old_ids["c.md"], new_ids["c.md"])

    def test_no_link_and_uncertain_are_explicit(self):
        self.put("a.md", "# Aurora launch\nSee [[b]].")
        self.put("b.md", "# Aurora reference\nDifferent matter.")
        source = self.indexed()
        none_result = suggest_for_note(self.db, source, provider=FakeProvider("none"),
                                       cache_path=self.cache, evaluate=True)
        self.assertEqual(none_result.judgments[0].relation, "none")
        self.assertIsNone(none_result.judgments[0].proposal_id)
        self.assertEqual(none_result.proposals, ())
        uncertain = suggest_for_note(self.db, source, provider=FakeProvider("unsure"),
                                     cache_path=self.root / "other.sqlite", evaluate=True)
        self.assertEqual(uncertain.judgments[0].relation, "unsure")
        self.assertEqual(uncertain.proposals, ())
        low_confidence = suggest_for_note(self.db, source, provider=FakeProvider("none", strength=.4),
                                          cache_path=self.root / "low.sqlite", evaluate=True)
        self.assertEqual(low_confidence.judgments[0].model_choice, "none")
        self.assertEqual(low_confidence.judgments[0].relation, "unsure")

    def test_failed_provider_call_is_not_cached_and_sources_unchanged(self):
        self.put("a.md", "# Aurora launch\nSee [[b]].")
        self.put("b.md", "# Aurora reference\nDetails.")
        source = self.indexed()
        original = {p.name: p.read_bytes() for p in self.vault.glob("*.md")}
        broken = FakeProvider(failure_after=0)
        with self.assertRaisesRegex(RuntimeError, "synthetic provider failure"):
            suggest_for_note(self.db, source, provider=broken,
                             cache_path=self.cache, evaluate=True)
        working = FakeProvider()
        result = suggest_for_note(self.db, source, provider=working,
                                  cache_path=self.cache, evaluate=True)
        self.assertEqual(result.provider_calls, 1)
        self.assertEqual(len(working.calls), 1)
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.vault.glob("*.md")})

    def test_cache_keeps_private_mode_separate_and_excludes_source_text(self):
        self.put("a.md", "# Aurora launch\nPRIVATE_SENTINEL_123 See [[b]].")
        self.put("b.md", "# Aurora reference\nOther detail.")
        source = self.indexed()
        provider = FakeProvider()
        suggest_for_note(self.db, source, provider=provider, cache_path=self.cache,
                         evaluate=True, private=False)
        private = suggest_for_note(self.db, source, provider=provider, cache_path=self.cache,
                                   evaluate=True, private=True)
        self.assertEqual(private.provider_calls, 1)
        self.assertEqual(len(provider.calls), 2)
        self.assertNotIn(b"PRIVATE_SENTINEL_123", self.cache.read_bytes())
        with self.assertRaisesRegex(ValueError, "outside the source vault"):
            suggest_for_note(self.db, source, provider=provider,
                             cache_path=self.vault / "cache.sqlite", evaluate=True)
        self.assertFalse((self.vault / "cache.sqlite").exists())

    def test_provider_required_only_for_evaluation_and_cap_is_enforced(self):
        self.put("a.md", "# Aurora launch")
        source = self.indexed()
        with self.assertRaises(ValueError):
            suggest_for_note(self.db, source, evaluate=True)
        with self.assertRaises(ValueError):
            suggest_for_note(self.db, source, k=MAX_CANDIDATES + 1)


if __name__ == "__main__":
    unittest.main()
