from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from jev_second_brain.index import scan_and_index
from jev_second_brain.rerank import _validate_judgment, rerank_search


class FakeProvider:
    def __init__(self, choice: str = "supports", failure_at: int | None = None) -> None:
        self.choice = choice
        self.failure_at = failure_at
        self.calls: list[tuple[object, object, bool]] = []

    def evaluate(self, state, questions, *, private=True):
        self.calls.append((state, questions, private))
        if self.failure_at == len(self.calls):
            raise RuntimeError("synthetic upstream failure")
        probabilities = {
            "supports": .9 if self.choice == "supports" else .02,
            "related": .08 if self.choice == "supports" else .08,
            "irrelevant": .02 if self.choice == "supports" else .9,
        }
        return SimpleNamespace(answers={"relevance": {
            "type": "choice", "choice": self.choice,
            "probabilities": probabilities,
        }})


class RerankTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.db = self.root / "state" / "index.sqlite"
        self.cache = self.root / "state" / "rerank.sqlite"
        (self.vault / "alpha.md").write_text("# Alpha\nThe blue telescope observes stars.\n")
        (self.vault / "beta.md").write_text("# Beta\nA telescope has a mirror for stars.\n")
        (self.vault / "gamma.md").write_text("# Gamma\nWe bought a telescope yesterday.\n")
        scan_and_index(self.vault, self.db)

    def test_local_search_needs_no_provider_or_cache(self) -> None:
        result = rerank_search(self.db, "telescope", k=2, cache_path=self.cache)
        self.assertEqual(result.mode, "local")
        self.assertEqual(result.answer_status, "unassessed")
        self.assertEqual(len(result.hits), 2)
        self.assertFalse(self.cache.exists())
        for hit in result.hits:
            self.assertTrue(Path(hit.source_path).is_file())
            self.assertEqual(len(hit.content_hash), 64)
            self.assertIsNone(hit.classification)

    def test_evaluation_is_bounded_and_cached_by_query_and_hash(self) -> None:
        provider = FakeProvider()
        first = rerank_search(
            self.db, "telescope", k=2, evaluate=True, provider=provider,
            cache_path=self.cache,
        )
        self.assertEqual(first.mode, "jev")
        self.assertEqual(first.answer_status, "supported")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len(first.hits), 2)
        self.assertTrue(all(hit.classification == "supports" for hit in first.hits))
        self.assertTrue(all(call[2] for call in provider.calls))
        self.assertTrue(all(len(call[1]) == 1 for call in provider.calls))
        before = {path.name: path.read_bytes() for path in self.vault.iterdir()}
        replay = rerank_search(
            self.db, "telescope", k=2, evaluate=True, provider=provider,
            cache_path=self.cache,
        )
        self.assertEqual(replay.mode, "jev")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.vault.iterdir()})
        self.assertNotIn(b"blue telescope", self.cache.read_bytes())

    def test_no_support_abstains_and_empty_query_never_calls_provider(self) -> None:
        provider = FakeProvider(choice="irrelevant")
        no_match = rerank_search(self.db, "nonexistentterm", evaluate=True, provider=provider)
        self.assertEqual(no_match.answer_status, "abstain")
        self.assertEqual(no_match.hits, ())
        result = rerank_search(self.db, "telescope", k=2, evaluate=True, provider=provider)
        self.assertEqual(result.answer_status, "abstain")
        self.assertEqual(result.mode, "jev")
        self.assertEqual(len(provider.calls), 2)
        self.assertFalse(any(hit.supported for hit in result.hits))

    def test_changed_note_misses_cache(self) -> None:
        provider = FakeProvider()
        rerank_search(self.db, "telescope", k=3, evaluate=True, provider=provider, cache_path=self.cache)
        self.assertEqual(len(provider.calls), 3)
        (self.vault / "alpha.md").write_text("# Alpha\nThe new telescope observes stars.\n")
        scan_and_index(self.vault, self.db)
        rerank_search(self.db, "telescope", k=3, evaluate=True, provider=provider, cache_path=self.cache)
        self.assertEqual(len(provider.calls), 4)
        rerank_search(self.db, "mirror", k=3, evaluate=True, provider=provider, cache_path=self.cache)
        self.assertEqual(len(provider.calls), 5)

    def test_private_and_public_judgments_use_separate_cache_keys(self) -> None:
        provider = FakeProvider()
        rerank_search(self.db, "telescope", k=1, evaluate=True, private=False,
                      provider=provider, cache_path=self.cache)
        rerank_search(self.db, "telescope", k=1, evaluate=True, private=True,
                      provider=provider, cache_path=self.cache)
        self.assertEqual(len(provider.calls), 2)

    def test_nonfinite_probability_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _validate_judgment({"type": "choice", "choice": "supports", "probabilities": {
                "supports": float("nan"), "related": 0.0, "irrelevant": 0.0,
            }})

    def test_hard_cap_limits_requested_evaluations(self) -> None:
        for number in range(25):
            (self.vault / f"extra-{number:02}.md").write_text(
                f"# Extra {number}\nTelescope observation number {number}.\n"
            )
        scan_and_index(self.vault, self.db)
        provider = FakeProvider()
        result = rerank_search(self.db, "telescope", k=100, evaluate=True, provider=provider, cache_path=self.cache)
        self.assertEqual(len(result.hits), 20)
        self.assertEqual(len(provider.calls), 20)

    def test_failure_returns_clearly_labeled_local_order(self) -> None:
        provider = FakeProvider(failure_at=2)
        result = rerank_search(self.db, "telescope", k=3, evaluate=True, provider=provider, cache_path=self.cache)
        self.assertEqual(result.mode, "fallback")
        self.assertEqual(result.answer_status, "unassessed")
        self.assertIn("RuntimeError", result.error or "")
        self.assertEqual(len(result.hits), 3)
        self.assertTrue(all(hit.classification is None for hit in result.hits))
        self.assertEqual(len(provider.calls), 2)


if __name__ == "__main__":
    unittest.main()
