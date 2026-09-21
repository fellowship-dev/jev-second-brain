#!/usr/bin/env python3
"""Run the frozen local candidate recall benchmark and print deterministic JSON."""

from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jev_second_brain.candidates import candidates_for_note  # noqa: E402
from jev_second_brain.index import list_notes, scan_and_index  # noqa: E402


BENCHMARK = Path(__file__).resolve().parent
DEFAULT_CORPUS = BENCHMARK / "corpus"
DEFAULT_TRUTH = BENCHMARK / "truth.json"


def fixture_fingerprint(corpus: Path = DEFAULT_CORPUS, truth_path: Path = DEFAULT_TRUTH) -> str:
    """Hash relative paths and bytes so benchmark revisions are visible."""
    digest = sha256()
    inputs = [truth_path, *sorted(corpus.rglob("*.md"))]
    for path in inputs:
        relative = path.relative_to(BENCHMARK).as_posix() if path.is_relative_to(BENCHMARK) else path.name
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_truth(truth: dict[str, Any], corpus: Path) -> None:
    cases = truth.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("truth must contain non-empty cases")
    case_ids: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise ValueError("case ids must be unique non-empty strings")
        case_ids.add(case_id)
        source = case.get("source")
        if not isinstance(source, str) or not (corpus / source).is_file():
            raise ValueError(f"missing source for case {case_id}: {source}")
        expected = case.get("expected")
        if not isinstance(expected, list) or not expected:
            raise ValueError(f"case {case_id} must have expected relationships")
        for item in expected:
            target = item.get("path")
            if target == source or not isinstance(target, str) or not (corpus / target).is_file():
                raise ValueError(f"invalid expected target for case {case_id}: {target}")
            if not item.get("relationship") or not item.get("direction"):
                raise ValueError(f"expected target lacks typed truth in case {case_id}")
        for target in case.get("forbidden", []):
            if target == source or not isinstance(target, str) or not (corpus / target).is_file():
                raise ValueError(f"invalid forbidden target for case {case_id}: {target}")


def run_benchmark(
    *, corpus: Path = DEFAULT_CORPUS, truth_path: Path = DEFAULT_TRUTH, k: int | None = None
) -> dict[str, Any]:
    """Return stable candidate recall metrics and traces for a frozen corpus."""
    corpus = Path(corpus).resolve()
    truth_path = Path(truth_path).resolve()
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    _validate_truth(truth, corpus)
    effective_k = truth["default_k"] if k is None else k
    if not isinstance(effective_k, int) or effective_k < 1:
        raise ValueError("k must be a positive integer")

    relationship_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    total_hits = total_expected = forbidden_hits = forbidden_total = 0
    traces: list[dict[str, Any]] = []
    with TemporaryDirectory(prefix="secondbrain-benchmark-") as temporary:
        database = Path(temporary) / "index.sqlite"
        scan_and_index(corpus, database)
        notes = {note.path: note for note in list_notes(database)}
        for case in truth["cases"]:
            source = notes[case["source"]]
            shortlist = candidates_for_note(database, source.id, k=effective_k)
            ranks = {candidate.path: rank for rank, candidate in enumerate(shortlist.candidates, start=1)}
            expected_trace = []
            case_hits = 0
            for expected in case["expected"]:
                found = expected["path"] in ranks
                case_hits += int(found)
                relationship_counts[expected["relationship"]][0] += int(found)
                relationship_counts[expected["relationship"]][1] += 1
                expected_trace.append({
                    **expected,
                    "found": found,
                    "rank": ranks.get(expected["path"]),
                })
            forbidden_trace = []
            for path in case.get("forbidden", []):
                found = path in ranks
                forbidden_hits += int(found)
                forbidden_total += 1
                forbidden_trace.append({"path": path, "found": found, "rank": ranks.get(path)})
            expected_count = len(case["expected"])
            total_hits += case_hits
            total_expected += expected_count
            traces.append({
                "id": case["id"],
                "source": case["source"],
                "k": effective_k,
                "hits": case_hits,
                "expected_count": expected_count,
                "recall_at_k": round(case_hits / expected_count, 6),
                "expected": expected_trace,
                "forbidden": forbidden_trace,
                "shortlist": [
                    {
                        "rank": rank,
                        "path": candidate.path,
                        "score": round(candidate.score, 6),
                        "reasons": list(candidate.reasons),
                    }
                    for rank, candidate in enumerate(shortlist.candidates, start=1)
                ],
                "coverage": {
                    "eligible": shortlist.eligible_count,
                    "pool": shortlist.pool_count,
                    "returned": shortlist.returned_count,
                    "truncated": shortlist.truncated_count,
                },
            })

    per_relationship = {
        relationship: {
            "hits": counts[0],
            "expected": counts[1],
            "recall_at_k": round(counts[0] / counts[1], 6),
        }
        for relationship, counts in sorted(relationship_counts.items())
    }
    return {
        "benchmark": "candidate-recall",
        "benchmark_version": truth["benchmark_version"],
        "fixture_fingerprint": fixture_fingerprint(corpus, truth_path),
        "k": effective_k,
        "primary_metric": "micro_recall_at_k",
        "primary_score": round(total_hits / total_expected, 6),
        "summary": {
            "hits": total_hits,
            "expected": total_expected,
            "forbidden_hits": forbidden_hits,
            "forbidden_expected_absent": forbidden_total,
            "negative_intrusion_rate": round(forbidden_hits / forbidden_total, 6) if forbidden_total else 0.0,
        },
        "per_relationship": per_relationship,
        "cases": traces,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, help="candidate cutoff (default: truth.json default_k)")
    parser.add_argument("--compact", action="store_true", help="emit JSON on one line")
    arguments = parser.parse_args(argv)
    result = run_benchmark(k=arguments.k)
    print(json.dumps(result, indent=None if arguments.compact else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
