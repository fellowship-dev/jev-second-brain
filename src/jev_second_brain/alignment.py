"""One-new-note alignment with a bounded local shortlist and typed pair judgments.

The index owns source text and candidate discovery. This module sends at most
one short pair per shortlisted note to an injected evaluator, then stores only
the typed answer and provenance in a local, revision-keyed cache. It never
changes Markdown or promotes a suggested relationship to a fact.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any

from .candidates import CandidateSet, candidates_for_note
from .index import Note, _connect, get_note
from .provider import MODEL, EvaluationResult, ProviderError, validate_answers
from .reviews import proposal_id


MAX_CANDIDATES = 50
MAX_NOTE_BYTES = 6_000
MIN_LINK_PROBABILITY = 0.65
LINK_RELATIONS = frozenset({"duplicate", "related", "revises", "contradicts"})
RUBRIC: dict[str, Any] = {
    "relation": {
        "type": "choice",
        "instructions": (
            "Judge the directed relationship from SOURCE to TARGET using only the "
            "shown note text. Prefer unsure if either excerpt lacks the evidence. "
            "Do not infer a link from shared generic words or fabricate chronology."
        ),
        "criteria": {
            "duplicate": "Same substantive claims or information; a human might consolidate them.",
            "related": "Distinct but meaningfully connected information worth a cross-link.",
            "revises": "SOURCE explicitly updates, corrects, or supersedes TARGET.",
            "contradicts": "SOURCE and TARGET make incompatible substantive claims.",
            "none": "No useful semantic relation is supported by the shown text.",
            "unsure": "Evidence is insufficient or ambiguous, including truncated key context.",
        },
    }
}
RUBRIC_HASH = sha256(json.dumps(RUBRIC, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PairJudgment:
    source_id: str
    source_path: str
    source_revision: str
    target_id: str
    target_path: str
    target_revision: str
    relation: str  # duplicate, related, revises, contradicts, none, unsure
    model_choice: str  # raw top-ranked typed choice, before local abstention threshold
    score: float  # probability of model_choice, not a calibrated correctness rate
    probabilities: dict[str, float]
    proposal_id: str | None
    model: str
    rubric_hash: str
    generation_id: str | None
    routing: dict[str, Any]
    input_tokens: int
    output_tokens: int
    cost_usd: str
    from_cache: bool


@dataclass(frozen=True)
class AlignmentResult:
    candidates: CandidateSet
    judgments: tuple[PairJudgment, ...]
    proposals: tuple[PairJudgment, ...]
    evaluated_count: int
    cache_hits: int
    pending_count: int  # cache misses before optional evaluation
    provider_calls: int


def _brief(content: str) -> tuple[str, bool]:
    encoded = content.encode("utf-8")
    if len(encoded) <= MAX_NOTE_BYTES:
        return content, False
    # The byte cap keeps a two-note JSON request under the provider's default
    # local request limit even when the source contains multi-byte characters.
    return encoded[:MAX_NOTE_BYTES].decode("utf-8", errors="ignore"), True


def _pair_state(source: Note, target: Note) -> dict[str, Any]:
    source_text, source_truncated = _brief(source.content)
    target_text, target_truncated = _brief(target.content)
    return {
        "source_id": source.id,
        "source_path": source.path,
        "source_title": source.title,
        "source_revision": source.content_hash,
        "source_text": source_text,
        "source_truncated": source_truncated,
        "target_id": target.id,
        "target_path": target.path,
        "target_title": target.title,
        "target_revision": target.content_hash,
        "target_text": target_text,
        "target_truncated": target_truncated,
    }


def _cache_key(source: Note, target: Note, *, private: bool) -> str:
    # Paths are shown to the model, so a rename must also invalidate this
    # judgment. Privacy mode prevents a public-mode answer from being reused
    # as though it had passed the private-route gate.
    identity = [
        MODEL, RUBRIC_HASH, private,
        source.id, source.path, source.content_hash,
        target.id, target.path, target.content_hash,
    ]
    return sha256(json.dumps(identity, separators=(",", ":")).encode("utf-8")).hexdigest()


def _vault_for_index(db_path: Path) -> Path:
    with closing(_connect(db_path, read_only=True)) as connection:
        row = connection.execute("SELECT value FROM metadata WHERE key='vault'").fetchone()
    if row is None:
        raise ValueError("Index has no vault metadata; run index first")
    return Path(row["value"]).resolve()


def _open_cache(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS pair_judgments (cache_key TEXT PRIMARY KEY, outcome TEXT NOT NULL)"
    )
    return connection


def _open_existing_cache(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)


def _cached(cache: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    row = cache.execute("SELECT outcome FROM pair_judgments WHERE cache_key=?", (key,)).fetchone()
    if row is None:
        return None
    try:
        outcome = json.loads(row[0])
    except ValueError as exc:
        raise ValueError("Alignment cache contains invalid JSON") from exc
    if not isinstance(outcome, dict) or outcome.get("model") != MODEL or outcome.get("rubric_hash") != RUBRIC_HASH:
        raise ValueError("Alignment cache entry has invalid provenance")
    validate_answers(outcome.get("answers"), RUBRIC)
    return outcome


def _outcome(result: EvaluationResult) -> dict[str, Any]:
    if not isinstance(result, EvaluationResult) or result.model != MODEL:
        raise ProviderError("alignment evaluator returned the wrong model")
    answers = validate_answers(result.answers, RUBRIC)
    route_fields = ("originalModelId", "resolvedProvider", "finalProvider", "planningReasoning")
    routing = {key: result.routing[key] for key in route_fields
               if isinstance(result.routing.get(key), (str, bool))}
    return {
        "model": result.model,
        "rubric_hash": RUBRIC_HASH,
        "answers": answers,
        "generation_id": result.generation_id,
        "routing": routing,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": str(result.cost_usd),
    }


def _judgment(source: Note, target: Note, outcome: dict[str, Any], *, from_cache: bool) -> PairJudgment:
    answer = outcome["answers"]["relation"]
    probabilities = {key: float(value) for key, value in answer["probabilities"].items()}
    choice = answer["choice"]
    score = probabilities[choice]
    relation = choice if score >= MIN_LINK_PROBABILITY else "unsure"
    identity = proposal_id(source.id, source.content_hash, target.id, target.content_hash, relation) \
        if relation in LINK_RELATIONS else None
    return PairJudgment(
        source_id=source.id, source_path=source.path, source_revision=source.content_hash,
        target_id=target.id, target_path=target.path, target_revision=target.content_hash,
        relation=relation, model_choice=choice, score=score, probabilities=probabilities,
        proposal_id=identity, model=outcome["model"], rubric_hash=RUBRIC_HASH,
        generation_id=outcome.get("generation_id"),
        routing=dict(outcome.get("routing", {})),
        input_tokens=outcome["input_tokens"], output_tokens=outcome["output_tokens"],
        cost_usd=outcome["cost_usd"], from_cache=from_cache,
    )


def suggest_for_note(
    db_path: Path,
    note_id: str,
    *,
    k: int = 20,
    provider: Any = None,
    cache_path: Path | None = None,
    private: bool = True,
    evaluate: bool = False,
) -> AlignmentResult:
    """Shortlist one note; optionally judge each candidate with one Jev request.

    With ``evaluate=False`` this is local and read-only. With ``evaluate=True``
    ``provider`` must expose ``evaluate(state, questions, private=...)``. The
    caller is responsible for verified private-route setup; this function
    invokes the provider only on cache misses, so a replay can make zero calls.
    """
    if type(k) is not int or not 1 <= k <= MAX_CANDIDATES:
        raise ValueError(f"k must be between 1 and {MAX_CANDIDATES}")
    if evaluate and provider is None:
        raise ValueError("evaluation requires an injected provider")
    db_path = Path(db_path).resolve()
    shortlist = candidates_for_note(db_path, note_id, k=k)
    if not shortlist.candidates:
        return AlignmentResult(shortlist, (), (), 0, 0, 0, 0)
    source = get_note(db_path, note_id)
    if source is None:
        raise ValueError(f"Unknown active note id: {note_id}")
    vault = _vault_for_index(db_path)
    state_path = Path(cache_path).resolve() if cache_path is not None else db_path.parent / "alignment-cache.sqlite"
    if state_path.is_relative_to(vault):
        raise ValueError("Put the alignment cache outside the source vault")
    if not evaluate:
        if not state_path.exists():
            return AlignmentResult(shortlist, (), (), 0, 0, len(shortlist.candidates), 0)
        cache_hits = 0
        with closing(_open_existing_cache(state_path)) as cache:
            for candidate in shortlist.candidates:
                target = get_note(db_path, candidate.note_id)
                if target is None:
                    raise ValueError("Candidate disappeared during alignment; rescan and retry")
                if _cached(cache, _cache_key(source, target, private=private)) is not None:
                    cache_hits += 1
        return AlignmentResult(
            shortlist, (), (), 0, cache_hits, len(shortlist.candidates) - cache_hits, 0
        )
    judgments: list[PairJudgment] = []
    cache_hits = provider_calls = 0
    with closing(_open_cache(state_path)) as cache:
        for candidate in shortlist.candidates:
            target = get_note(db_path, candidate.note_id)
            if target is None:
                # An index mutation during this read should fail rather than
                # silently produce an incomplete coverage receipt.
                raise ValueError("Candidate disappeared during alignment; rescan and retry")
            key = _cache_key(source, target, private=private)
            outcome = _cached(cache, key)
            from_cache = outcome is not None
            if from_cache:
                cache_hits += 1
            else:
                result = provider.evaluate(_pair_state(source, target), RUBRIC, private=private)
                provider_calls += 1
                outcome = _outcome(result)
                with cache:
                    cache.execute(
                        "INSERT OR REPLACE INTO pair_judgments(cache_key,outcome) VALUES(?,?)",
                        (key, json.dumps(outcome, ensure_ascii=False, sort_keys=True, allow_nan=False)),
                    )
            judgments.append(_judgment(source, target, outcome, from_cache=from_cache))
    proposed = tuple(judgment for judgment in judgments if judgment.relation in LINK_RELATIONS)
    return AlignmentResult(shortlist, tuple(judgments), proposed, len(judgments),
                           cache_hits, provider_calls, provider_calls)
