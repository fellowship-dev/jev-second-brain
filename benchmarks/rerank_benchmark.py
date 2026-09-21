"""Frozen reducer benchmark for mocked Jev query judgments.

This measures deterministic behavior around fixed typed judgments.  It does
not claim to measure live model quality or full-text candidate recall.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from math import log2
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jev_second_brain.index import scan_and_index  # noqa: E402
from jev_second_brain.rerank import rerank_search  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "rerank_cases.json"
GAIN = {"supports": 3.0, "related": 1.0, "irrelevant": 0.0}


@dataclass(frozen=True)
class BenchmarkReport:
    fixture_fingerprint: str
    ranking: float
    abstention: float
    fallback: float
    cache: float
    bounds: float
    total: float
    hard_failures: tuple[str, ...]


class FrozenProvider:
    """Return fixture judgments by exact note content; never infer semantics."""

    private_route_verified = True

    def __init__(self, judgments: dict[str, dict[str, Any]], *, failure_at: int | None = None) -> None:
        self.judgments = judgments
        self.failure_at = failure_at
        self.calls: list[dict[str, Any]] = []

    def evaluate(self, state, questions, *, private=True):
        self.calls.append(state)
        if self.failure_at == len(self.calls):
            raise RuntimeError("frozen provider failure")
        judgment = self.judgments[state["note_excerpt"]]
        return SimpleNamespace(answers={"relevance": {"type": "choice", **judgment}})


def _dcg(labels: list[str]) -> float:
    return sum(GAIN[label] / log2(rank + 2) for rank, label in enumerate(labels))


def _ndcg(labels: list[str]) -> float:
    ideal = sorted(labels, key=GAIN.get, reverse=True)
    denominator = _dcg(ideal)
    return _dcg(labels) / denominator if denominator else 1.0


def _write_case(root: Path, case: dict[str, Any]) -> tuple[Path, Path, dict[str, dict[str, Any]]]:
    vault = root / "vault"
    vault.mkdir(parents=True)
    judgments = {}
    for note in case["notes"]:
        content = note["content"]
        (vault / note["path"]).write_text(content, encoding="utf-8")
        judgments[content] = {"choice": note["choice"], "probabilities": note["probabilities"]}
    db = root / "state" / "index.sqlite"
    scan_and_index(vault, db)
    return vault, db, judgments


def run_benchmark(fixture_path: Path = FIXTURE) -> BenchmarkReport:
    fixture_bytes = Path(fixture_path).read_bytes()
    fixture = json.loads(fixture_bytes)
    if fixture.get("schema") != 1 or not fixture.get("ranking_cases"):
        raise ValueError("rerank fixture must use schema 1 with ranking cases")
    ndcgs: list[float] = []
    statuses: list[bool] = []
    hard_failures: list[str] = []
    with TemporaryDirectory() as temporary:
        base = Path(temporary)
        for index, case in enumerate(fixture["ranking_cases"]):
            _, db, judgments = _write_case(base / f"ranking-{index}", case)
            provider = FrozenProvider(judgments)
            result = rerank_search(
                db, case["query"], k=20, evaluate=True, provider=provider,
                cache_path=base / f"ranking-{index}" / "state" / "cache.sqlite",
            )
            labels = [hit.classification for hit in result.hits]
            ndcgs.append(_ndcg(labels))
            statuses.append(result.answer_status == case["expected_status"])
            if result.answer_status == "supported" and not any(
                hit.classification == "supports" and (hit.support_probability or 0) >= .60
                for hit in result.hits
            ):
                hard_failures.append(f"{case['id']}: unsupported confidence")

        # A mid-stream provider failure must discard every partial judgment.
        case = fixture["ranking_cases"][0]
        _, db, judgments = _write_case(base / "failure", case)
        local = rerank_search(db, case["query"], k=20)
        failing = FrozenProvider(judgments, failure_at=2)
        failed = rerank_search(
            db, case["query"], k=20, evaluate=True, provider=failing,
            cache_path=base / "failure" / "state" / "cache.sqlite",
        )
        fallback_checks = (
            failed.mode == "fallback",
            failed.answer_status == "unassessed",
            [hit.id for hit in failed.hits] == [hit.id for hit in local.hits],
            all(hit.classification is None and not hit.supported for hit in failed.hits),
            len(failing.calls) == 2,
        )
        if not all(fallback_checks[:4]):
            hard_failures.append("provider failure leaked a partial or confident result")

        # Cache behavior is measured through provider call deltas, not storage layout.
        _, db, judgments = _write_case(base / "cache", case)
        cache_path = base / "cache" / "state" / "cache.sqlite"
        provider = FrozenProvider(judgments)
        first = rerank_search(db, case["query"], k=20, evaluate=True, provider=provider, cache_path=cache_path)
        first_calls = len(provider.calls)
        rerank_search(db, case["query"], k=20, evaluate=True, provider=provider, cache_path=cache_path)
        replay_delta = len(provider.calls) - first_calls
        public_before = len(provider.calls)
        rerank_search(
            db, case["query"], k=20, evaluate=True, private=False,
            provider=provider, cache_path=cache_path,
        )
        privacy_delta = len(provider.calls) - public_before
        query_before = len(provider.calls)
        rerank_search(
            db, case["query"] + " stars", k=20, evaluate=True,
            provider=provider, cache_path=cache_path,
        )
        query_delta = len(provider.calls) - query_before
        changed = case["notes"][0]
        changed_content = changed["content"] + "Updated evidence.\n"
        source = base / "cache" / "vault" / changed["path"]
        source.write_text(changed_content, encoding="utf-8")
        judgments[changed_content] = judgments[changed["content"]]
        scan_and_index(base / "cache" / "vault", db)
        changed_before = len(provider.calls)
        rerank_search(db, case["query"], k=20, evaluate=True, provider=provider, cache_path=cache_path)
        changed_delta = len(provider.calls) - changed_before
        raw_cache = cache_path.read_bytes()
        cache_checks = (
            first_calls == len(first.hits), replay_delta == 0,
            privacy_delta == len(first.hits), query_delta == len(first.hits),
            changed_delta == 1,
            case["query"].encode() not in raw_cache and changed["content"].encode() not in raw_cache,
        )
        if privacy_delta != len(first.hits):
            hard_failures.append("public and private cache entries were reused")

        # No candidate means no provider call. A large result set stays capped at 20.
        no_match_before = len(provider.calls)
        no_match = rerank_search(db, "zzznomatchzzz", k=100, evaluate=True, provider=provider, cache_path=cache_path)
        no_match_ok = no_match.answer_status == "abstain" and not no_match.hits and len(provider.calls) == no_match_before
        cap_root = base / "cap"
        cap_vault = cap_root / "vault"
        cap_vault.mkdir(parents=True)
        cap_judgments = {}
        for number in range(25):
            content = f"# Item {number}\nBounded telescope evidence {number}.\n"
            (cap_vault / f"{number:02}.md").write_text(content)
            cap_judgments[content] = {
                "choice": "related",
                "probabilities": {"supports": .1, "related": .8, "irrelevant": .1},
            }
        cap_db = cap_root / "state" / "index.sqlite"
        scan_and_index(cap_vault, cap_db)
        cap_provider = FrozenProvider(cap_judgments)
        capped = rerank_search(
            cap_db, "telescope", k=100, evaluate=True, provider=cap_provider,
            cache_path=cap_root / "state" / "cache.sqlite",
        )
        cap_ok = len(capped.hits) == len(cap_provider.calls) == 20

    ranking = 35 * sum(ndcgs) / len(ndcgs)
    abstention = 20 * sum(statuses) / len(statuses)
    fallback = 20 * sum(fallback_checks) / len(fallback_checks)
    cache = 20 * sum(cache_checks) / len(cache_checks)
    bounds = 2.5 * int(no_match_ok) + 2.5 * int(cap_ok)
    total = 0.0 if hard_failures else ranking + abstention + fallback + cache + bounds
    return BenchmarkReport(
        fixture_fingerprint=sha256(fixture_bytes).hexdigest(),
        ranking=round(ranking, 3), abstention=round(abstention, 3),
        fallback=round(fallback, 3), cache=round(cache, 3),
        bounds=round(bounds, 3), total=round(total, 3),
        hard_failures=tuple(hard_failures),
    )


if __name__ == "__main__":
    print(json.dumps(asdict(run_benchmark()), indent=2, sort_keys=True))
