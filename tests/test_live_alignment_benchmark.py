import contextlib
from decimal import Decimal
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from benchmarks.live_alignment import HOLDOUT_FIXTURE, FIXTURE, load_fixture, main, run_benchmark
from jev_second_brain.policy import BudgetLimits, BudgetMeter


FROZEN_FINGERPRINT = "a6f5d73dddf70bc40249cbf489d1ac3361283c0e11fd6637d8e1e872a56f8707"
HOLDOUT_FINGERPRINT = "87a22df434ffc3902e23b4a0256b4692e4f7d0cee53f5b38a6376d45ba7313b5"
PREDICTIONS = {
    "Archive verification": "duplicate",
    "Falcon readiness conversation": "related",
    "Current receipt retention decision": "related",  # acceptable but deliberately inexact
    "Offline test result": "contradicts",
    "Orchid launch checklist": "none",
    "Follow-up fragment": "unsure",
}


class FakeProvider:
    def __init__(self, *, limits=None, env=None):
        self.budget = BudgetMeter(limits or BudgetLimits(max_requests=6))
        self.calls = []
        self.predictions = PREDICTIONS

    def evaluate(self, state, questions, *, private=True):
        self.calls.append((state, questions, private))
        encoded = json.dumps({"state": state, "questions": questions}).encode()
        self.budget.reserve_attempt(len(encoded))
        self.budget.record_response(10, 2, Decimal("0.001"))
        predicted = self.predictions[state["source"]["title"]]
        probabilities = {label: float(label == predicted) for label in
                         ("duplicate", "related", "revises", "contradicts", "none", "unsure")}
        return SimpleNamespace(
            answers={"relation": {"type": "choice", "choice": predicted, "probabilities": probabilities}}
        )


class LiveAlignmentBenchmarkTest(unittest.TestCase):
    def test_fixture_is_frozen_and_covers_each_relation(self):
        fixture, fingerprint = load_fixture()
        self.assertEqual(fingerprint, FROZEN_FINGERPRINT)
        self.assertEqual(len(fixture["cases"]), 6)
        self.assertEqual(
            {case["expected"] for case in fixture["cases"]},
            {"duplicate", "related", "revises", "contradicts", "none", "unsure"},
        )
        self.assertTrue(all(case["expected"] in case["acceptable"] for case in fixture["cases"]))

    def test_holdout_is_frozen_and_covers_boundary_and_failure_classes(self):
        fixture, fingerprint = load_fixture(HOLDOUT_FIXTURE)
        self.assertEqual(fingerprint, HOLDOUT_FINGERPRINT)
        self.assertEqual(len(fixture["cases"]), 12)
        ids = {case["id"] for case in fixture["cases"]}
        self.assertGreaterEqual(sum(case_id.startswith("boundary-") for case_id in ids), 4)
        self.assertEqual(
            {case["expected"] for case in fixture["cases"]},
            {"duplicate", "related", "revises", "contradicts", "none", "unsure"},
        )
        self.assertTrue(any(case_id.startswith("revision-direction-") for case_id in ids))
        self.assertEqual(sum(case_id.startswith("contradiction-") for case_id in ids), 2)
        self.assertEqual(sum(case_id.startswith("none-shared-") for case_id in ids), 2)
        self.assertEqual(sum(case_id.startswith("unsure-") for case_id in ids), 2)

    def test_scoring_confusion_abstention_and_full_budget(self):
        provider = FakeProvider()
        report = run_benchmark(provider)
        self.assertEqual(report["exact_accuracy"], 0.833333)
        self.assertEqual(report["acceptable_accuracy"], 1.0)
        self.assertEqual(report["confusion_matrix"]["revises"]["related"], 1)
        self.assertEqual(report["abstention"], {"expected": 1, "predicted": 1, "correct": 1, "recall": 1.0})
        self.assertEqual(report["usage"]["requests"], 6)
        self.assertEqual(report["usage"]["input_tokens"], 60)
        self.assertEqual(report["usage"]["output_tokens"], 12)
        self.assertEqual(report["usage"]["cost_usd"], "0.006")
        self.assertTrue(all(call[2] is False for call in provider.calls))

    def test_effective_relation_applies_pipeline_confidence_threshold(self):
        class LowConfidenceProvider(FakeProvider):
            def evaluate(self, state, questions, *, private=True):
                if state["source"]["title"] != "Archive verification":
                    return super().evaluate(state, questions, private=private)
                self.calls.append((state, questions, private))
                encoded = json.dumps({"state": state, "questions": questions}).encode()
                self.budget.reserve_attempt(len(encoded))
                self.budget.record_response(10, 2, Decimal("0.001"))
                probabilities = {
                    "duplicate": .53, "related": .47, "revises": 0.0,
                    "contradicts": 0.0, "none": 0.0, "unsure": 0.0,
                }
                return SimpleNamespace(answers={"relation": {
                    "type": "choice", "choice": "duplicate", "probabilities": probabilities,
                }})

        report = run_benchmark(LowConfidenceProvider())
        trace = next(case for case in report["cases"] if case["id"] == "duplicate-checksum-procedure")
        self.assertEqual(trace["model_choice"], "duplicate")
        self.assertEqual(trace["predicted"], "unsure")
        self.assertEqual(trace["confidence"], .53)
        self.assertTrue(trace["threshold_applied"])
        self.assertFalse(trace["exact"])
        self.assertEqual(report["minimum_link_probability"], .65)
        self.assertEqual(report["confusion_matrix"]["duplicate"]["unsure"], 1)
        self.assertEqual(report["abstention"]["predicted"], 2)

    def test_report_contains_no_raw_note_text_or_provider_payload(self):
        fixture, _ = load_fixture()
        rendered = json.dumps(run_benchmark(FakeProvider()), sort_keys=True)
        for case in fixture["cases"]:
            self.assertNotIn(case["source"]["text"], rendered)
            self.assertNotIn(case["target"]["text"], rendered)
            self.assertNotIn(case["source"]["title"], rendered)
            self.assertNotIn(case["target"]["title"], rendered)
        self.assertNotIn("answers", rendered)
        self.assertNotIn("generation_id", rendered)
        self.assertNotIn("routing", rendered)

    def test_budget_too_small_fails_before_any_case(self):
        provider = FakeProvider(limits=BudgetLimits(max_requests=5))
        with self.assertRaisesRegex(ValueError, "at least the 6 frozen cases"):
            run_benchmark(provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(provider.budget.requests, 0)

    def test_cli_requires_public_flag_and_key_without_leaking_fixture(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            main([], env={})
        self.assertIn("--public", stderr.getvalue())

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            main(["--public"], env={})
        error = stderr.getvalue()
        self.assertIn("AI_GATEWAY_API_KEY is not configured", error)
        fixture, _ = load_fixture()
        for case in fixture["cases"]:
            self.assertNotIn(case["source"]["text"], error)
            self.assertNotIn(case["target"]["text"], error)

    def test_cli_writes_json_using_injected_provider(self):
        providers = []

        def factory(**kwargs):
            provider = FakeProvider(**kwargs)
            providers.append(provider)
            return provider

        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested" / "report.json"
            result = main(
                ["--public", "--max-requests", "6", "--max-cost-usd", "0.02", "--output", str(output)],
                provider_factory=factory,
                env={"AI_GATEWAY_API_KEY": "synthetic-test-key"},
            )
            self.assertEqual(result, 0)
            report = json.loads(output.read_text())
        self.assertEqual(report["fixture_fingerprint"], FROZEN_FINGERPRINT)
        self.assertEqual(report["usage"]["limits"]["max_cost_usd"], "0.02")
        self.assertEqual(len(providers[0].calls), 6)

    def test_custom_holdout_fixture_executes_and_reports_its_fingerprint(self):
        fixture, _ = load_fixture(HOLDOUT_FIXTURE)
        predictions = {case["source"]["title"]: case["expected"] for case in fixture["cases"]}
        providers = []

        def factory(**kwargs):
            provider = FakeProvider(**kwargs)
            provider.predictions = predictions
            providers.append(provider)
            return provider

        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "holdout.json"
            result = main(
                [
                    "--public", "--fixture", str(HOLDOUT_FIXTURE),
                    "--max-requests", "12", "--output", str(output),
                ],
                provider_factory=factory,
                env={"AI_GATEWAY_API_KEY": "synthetic-test-key"},
            )
            report = json.loads(output.read_text())
        self.assertEqual(result, 0)
        self.assertEqual(report["benchmark"], "live-synthetic-alignment-holdout")
        self.assertEqual(report["fixture_fingerprint"], HOLDOUT_FINGERPRINT)
        self.assertEqual(report["case_count"], 12)
        self.assertEqual(report["exact_accuracy"], 1.0)
        self.assertEqual(len(providers[0].calls), 12)


if __name__ == "__main__":
    unittest.main()
