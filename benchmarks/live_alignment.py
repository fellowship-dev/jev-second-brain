#!/usr/bin/env python3
"""Evaluate Jev's pair-alignment labels on frozen public synthetic cases."""

from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jev_second_brain.alignment import MIN_LINK_PROBABILITY, RUBRIC  # noqa: E402
from jev_second_brain.policy import BudgetLimits  # noqa: E402
from jev_second_brain.provider import VercelJevProvider  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "alignment_cases.json"
HOLDOUT_FIXTURE = Path(__file__).parent / "fixtures" / "alignment_holdout_cases.json"
LABELS = ("duplicate", "related", "revises", "contradicts", "none", "unsure")


def load_fixture(path: Path = FIXTURE) -> tuple[dict[str, Any], str]:
    raw = Path(path).read_bytes()
    fixture = json.loads(raw)
    if fixture.get("schema") != 1 or not isinstance(fixture.get("cases"), list) or not fixture["cases"]:
        raise ValueError("alignment fixture must use schema 1 with nonempty cases")
    ids: set[str] = set()
    for case in fixture["cases"]:
        case_id = case.get("id")
        expected = case.get("expected")
        acceptable = case.get("acceptable")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError("case ids must be unique nonempty strings")
        ids.add(case_id)
        if expected not in LABELS or not isinstance(acceptable, list) or expected not in acceptable:
            raise ValueError(f"case {case_id} has invalid expected labels")
        if not acceptable or any(label not in LABELS for label in acceptable):
            raise ValueError(f"case {case_id} has invalid acceptable labels")
        for side in ("source", "target"):
            note = case.get(side)
            if not isinstance(note, dict) or set(note) != {"title", "text"}:
                raise ValueError(f"case {case_id} has invalid {side}")
            if any(not isinstance(value, str) or not value.strip() for value in note.values()):
                raise ValueError(f"case {case_id} has empty {side}")
    return fixture, sha256(raw).hexdigest()


def run_benchmark(provider: Any, fixture_path: Path = FIXTURE) -> dict[str, Any]:
    """Run every case once through an injected public-mode provider."""
    fixture, fingerprint = load_fixture(fixture_path)
    case_count = len(fixture["cases"])
    budget = getattr(provider, "budget", None)
    if budget is None or not hasattr(budget, "limits"):
        raise ValueError("provider must expose a BudgetMeter as budget")
    if budget.limits.max_requests < case_count:
        raise ValueError(f"max_requests must be at least the {case_count} frozen cases")

    exact = acceptable = predicted_unsure = expected_unsure = abstention_correct = 0
    confusion: dict[str, dict[str, int]] = {
        expected: {predicted: 0 for predicted in LABELS} for expected in LABELS
    }
    traces: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        # These are committed public synthetic strings. Private mode is never
        # accepted by this benchmark and raw text is omitted from its report.
        state = {"source": case["source"], "target": case["target"]}
        result = provider.evaluate(state, RUBRIC, private=False)
        answer = result.answers["relation"]
        model_choice = answer["choice"]
        if model_choice not in LABELS:
            raise ValueError("provider returned an unknown alignment label")
        confidence = float(answer["probabilities"][model_choice])
        relation = model_choice if confidence >= MIN_LINK_PROBABILITY else "unsure"
        exact_match = relation == case["expected"]
        acceptable_match = relation in case["acceptable"]
        exact += int(exact_match)
        acceptable += int(acceptable_match)
        predicted_unsure += int(relation == "unsure")
        expected_unsure += int(case["expected"] == "unsure")
        abstention_correct += int(relation == case["expected"] == "unsure")
        confusion[case["expected"]][relation] += 1
        traces.append({
            "id": case["id"],
            "expected": case["expected"],
            "acceptable": list(case["acceptable"]),
            "model_choice": model_choice,
            "predicted": relation,
            "threshold_applied": relation != model_choice,
            "confidence": round(confidence, 6),
            "exact": exact_match,
            "acceptable_match": acceptable_match,
        })

    meter = provider.budget
    return {
        "benchmark": fixture["name"],
        "schema": fixture["schema"],
        "fixture_fingerprint": fingerprint,
        "model": "typesafe-ai/jev",
        "mode": "public_synthetic",
        "minimum_link_probability": MIN_LINK_PROBABILITY,
        "case_count": case_count,
        "exact_accuracy": round(exact / case_count, 6),
        "acceptable_accuracy": round(acceptable / case_count, 6),
        "confusion_matrix": confusion,
        "abstention": {
            "expected": expected_unsure,
            "predicted": predicted_unsure,
            "correct": abstention_correct,
            "recall": round(abstention_correct / expected_unsure, 6) if expected_unsure else None,
        },
        "usage": {
            "requests": meter.requests,
            "request_bytes": meter.request_bytes,
            "input_tokens": meter.input_tokens,
            "output_tokens": meter.output_tokens,
            "cost_usd": str(meter.cost_usd),
            "limits": {
                "max_requests": meter.limits.max_requests,
                "max_input_tokens": meter.limits.max_input_tokens,
                "max_cost_usd": str(meter.limits.max_cost_usd),
            },
        },
        "cases": traces,
    }


def _positive_decimal(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("must be a decimal amount") from exc
    if not amount.is_finite() or amount <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return amount


def main(
    argv: list[str] | None = None,
    *,
    provider_factory: Callable[..., Any] = VercelJevProvider,
    env: dict[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", action="store_true", required=True,
                        help="confirm that only committed public synthetic cases may be sent")
    parser.add_argument("--max-requests", type=int, default=6)
    parser.add_argument("--max-cost-usd", type=_positive_decimal, default=Decimal("0.10"))
    parser.add_argument("--fixture", type=Path, default=FIXTURE,
                        help="public synthetic fixture JSON (default: primary frozen set)")
    parser.add_argument("--output", type=Path, help="write JSON here instead of stdout")
    arguments = parser.parse_args(argv)
    environment = os.environ if env is None else env
    if not environment.get("AI_GATEWAY_API_KEY"):
        parser.error("AI_GATEWAY_API_KEY is not configured")
    fixture, _ = load_fixture(arguments.fixture)
    if arguments.max_requests < len(fixture["cases"]):
        parser.error(f"--max-requests must be at least {len(fixture['cases'])}")
    limits = BudgetLimits(
        max_requests=arguments.max_requests,
        max_cost_usd=arguments.max_cost_usd,
        max_retries=0,
    )
    provider = provider_factory(limits=limits, env=environment)
    report = run_benchmark(provider, arguments.fixture)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
