from __future__ import annotations

import unittest

from benchmarks.rerank_benchmark import run_benchmark


class RerankBenchmarkTest(unittest.TestCase):
    def test_frozen_baseline_meets_all_behavioral_checks(self) -> None:
        report = run_benchmark()
        self.assertEqual(
            report.fixture_fingerprint,
            "871bc9b829da4b7a261059fc31955e1d53895f8200c8e7a42c63ca99081bc32f",
        )
        self.assertEqual(report.hard_failures, ())
        self.assertEqual(report.ranking, 35.0)
        self.assertEqual(report.abstention, 20.0)
        self.assertEqual(report.fallback, 20.0)
        self.assertEqual(report.cache, 20.0)
        self.assertEqual(report.bounds, 5.0)
        self.assertEqual(report.total, 100.0)


if __name__ == "__main__":
    unittest.main()
