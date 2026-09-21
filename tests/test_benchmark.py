import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from benchmark.run import DEFAULT_CORPUS, DEFAULT_TRUTH, fixture_fingerprint, run_benchmark


FROZEN_FINGERPRINT = "01ae5789f03e21bc2134098927f9ac325550cccc3d22e086231596e23178a272"


class CandidateRecallBenchmarkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_benchmark()

    def test_frozen_fixture_and_baseline(self):
        self.assertEqual(fixture_fingerprint(), FROZEN_FINGERPRINT)
        self.assertEqual(self.result["benchmark_version"], 1)
        self.assertEqual(self.result["k"], 3)
        self.assertEqual(self.result["primary_metric"], "micro_recall_at_k")
        self.assertEqual(self.result["primary_score"], 0.833333)
        self.assertEqual(self.result["summary"]["hits"], 5)
        self.assertEqual(self.result["summary"]["expected"], 6)

    def test_relationship_scores_are_separate_and_direction_is_retained(self):
        scores = self.result["per_relationship"]
        self.assertEqual(
            set(scores),
            {"contradicts", "duplicate", "explicit_link", "outside_shortlist", "paraphrase", "supersedes"},
        )
        self.assertEqual(scores["outside_shortlist"]["recall_at_k"], 0.0)
        for relationship in set(scores) - {"outside_shortlist"}:
            self.assertEqual(scores[relationship]["recall_at_k"], 1.0)
        traces = {case["id"]: case for case in self.result["cases"]}
        self.assertEqual(traces["new-revises-old"]["expected"][0]["direction"], "source_to_target")
        self.assertEqual(traces["claim-contradicts-baseline"]["expected"][0]["direction"], "source_to_target")

    def test_k_is_a_real_bound_and_hard_negative_stays_out(self):
        for case in self.result["cases"]:
            self.assertLessEqual(len(case["shortlist"]), self.result["k"])
            self.assertEqual(case["coverage"]["returned"], len(case["shortlist"]))
            self.assertEqual(
                case["coverage"]["pool"],
                case["coverage"]["returned"] + case["coverage"]["truncated"],
            )
        paraphrase = next(case for case in self.result["cases"] if case["id"] == "different-title-paraphrase")
        self.assertFalse(paraphrase["forbidden"][0]["found"])
        self.assertEqual(paraphrase["hits"], 1)
        self.assertEqual(self.result["summary"]["forbidden_hits"], 0)
        self.assertEqual(self.result["summary"]["forbidden_expected_absent"], 1)
        self.assertEqual(self.result["summary"]["negative_intrusion_rate"], 0.0)

    def test_tighter_cutoff_preserves_the_strong_paraphrase(self):
        result = run_benchmark(k=1)
        self.assertEqual(result["primary_score"], 0.833333)
        paraphrase = next(case for case in result["cases"] if case["id"] == "different-title-paraphrase")
        self.assertEqual(paraphrase["shortlist"][0]["path"], "references/staged-delivery.md")
        self.assertTrue(paraphrase["expected"][0]["found"])
        self.assertFalse(paraphrase["forbidden"][0]["found"])

    def test_fixture_edits_change_fingerprint(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            corpus = root / "corpus"
            shutil.copytree(DEFAULT_CORPUS, corpus)
            truth = root / "truth.json"
            shutil.copy2(DEFAULT_TRUTH, truth)
            original = fixture_fingerprint(corpus, truth)
            changed = corpus / "queries" / "explicit-link.md"
            changed.write_text(changed.read_text() + "\nA benchmark revision.\n")
            self.assertNotEqual(fixture_fingerprint(corpus, truth), original)

    def test_truth_cannot_hide_expected_relationships(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            corpus = root / "corpus"
            shutil.copytree(DEFAULT_CORPUS, corpus)
            truth = json.loads(DEFAULT_TRUTH.read_text())
            truth["cases"][0]["expected"] = []
            truth_path = root / "truth.json"
            truth_path.write_text(json.dumps(truth))
            with self.assertRaisesRegex(ValueError, "expected relationships"):
                run_benchmark(corpus=corpus, truth_path=truth_path)


if __name__ == "__main__":
    unittest.main()
