"""Bounded, source-linked search reranking with an offline local fallback.

Jev classifies one query/note pair at a time.  Deterministic code owns local
recall, budgets, cache identity, ordering, source attribution and abstention.
The cache stores only typed judgments and digests, never note text or queries.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any

from .index import Note, SearchHit, get_note, search
from .provider import MODEL, VercelJevProvider


RUBRIC_VERSION = "query-support-v1"
MAX_RERANK_K = 20
MAX_QUERY_CHARS = 1000
MAX_EVIDENCE_CHARS = 3000
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_CRITERIA = {
    "supports": "The shown note text directly contains information that could support an answer to the query.",
    "related": "The shown note text concerns the topic but does not directly support an answer.",
    "irrelevant": "The shown note text does not meaningfully help with the query.",
}
_QUESTION = {
    "relevance": {
        "type": "choice",
        "instructions": "Classify whether the shown note excerpt can support the user's query. Judge only the shown text. Do not infer missing facts.",
        "criteria": _CRITERIA,
    }
}


@dataclass(frozen=True)
class RerankHit:
    id: str
    path: str
    source_path: str
    title: str
    excerpt: str
    content_hash: str
    local_score: float
    classification: str | None = None
    support_probability: float | None = None
    relevance_score: float | None = None
    supported: bool = False


@dataclass(frozen=True)
class RerankResult:
    query: str
    hits: tuple[RerankHit, ...]
    mode: str  # local, jev, fallback
    answer_status: str  # unassessed, supported, abstain
    evaluated: int
    cache_hits: int
    error: str | None = None


def _vault_root(db_path: Path) -> Path:
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute("SELECT value FROM metadata WHERE key='vault'").fetchone()
    if row is None:
        raise ValueError("Index has no vault root; run scan first")
    return Path(row[0]).resolve()


def _local_hit(hit: SearchHit, note: Note, vault_root: Path) -> RerankHit:
    source = (vault_root / note.path).resolve()
    if not source.is_relative_to(vault_root):
        raise ValueError("Indexed source path escapes the vault")
    return RerankHit(
        id=hit.id, path=hit.path, source_path=str(source), title=hit.title,
        excerpt=hit.excerpt, content_hash=note.content_hash, local_score=hit.score,
    )


def _evidence_excerpt(content: str, query: str) -> str:
    if len(content) <= MAX_EVIDENCE_CHARS:
        return content
    folded = content.casefold()
    positions = [folded.find(word.casefold()) for word in _WORDS.findall(query)[:16] if len(word) >= 3]
    positions = [position for position in positions if position >= 0]
    start = max(0, min(positions) - 400) if positions else 0
    return content[start : start + MAX_EVIDENCE_CHARS]


def _cache_key(query: str, content_hash: str, *, private: bool) -> str:
    identity = [MODEL, RUBRIC_VERSION, private, query, content_hash]
    return sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _open_cache(cache_path: Path) -> sqlite3.Connection:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(cache_path)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS judgments (
               key TEXT PRIMARY KEY,
               choice TEXT NOT NULL,
               probabilities TEXT NOT NULL
           )"""
    )
    return connection


def _read_cached(connection: sqlite3.Connection, key: str) -> tuple[str, dict[str, float]] | None:
    row = connection.execute("SELECT choice,probabilities FROM judgments WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    try:
        probabilities = json.loads(row[1])
        return _validate_judgment({"type": "choice", "choice": row[0], "probabilities": probabilities})
    except (TypeError, ValueError):
        return None


def _write_cached(connection: sqlite3.Connection, key: str, choice: str, probabilities: dict[str, float]) -> None:
    with connection:
        connection.execute(
            "INSERT OR REPLACE INTO judgments(key,choice,probabilities) VALUES(?,?,?)",
            (key, choice, json.dumps(probabilities, sort_keys=True, separators=(",", ":"))),
        )


def _validate_judgment(answer: Any) -> tuple[str, dict[str, float]]:
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise ValueError("Jev relevance answer has the wrong type")
    probabilities = answer.get("probabilities")
    choice = answer.get("choice")
    if not isinstance(probabilities, dict) or set(probabilities) != set(_CRITERIA) or choice not in _CRITERIA:
        raise ValueError("Jev relevance answer has invalid criteria")
    if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1
           for value in probabilities.values()):
        raise ValueError("Jev relevance probabilities are invalid")
    if not .98 <= sum(probabilities.values()) <= 1.02:
        raise ValueError("Jev relevance probabilities do not sum to one")
    if probabilities[choice] < max(probabilities.values()) - 1e-9:
        raise ValueError("Jev choice is inconsistent with probabilities")
    return choice, {key: float(value) for key, value in probabilities.items()}


def _assessed(hit: RerankHit, judgment: tuple[str, dict[str, float]]) -> RerankHit:
    choice, probabilities = judgment
    support = probabilities["supports"]
    return replace(
        hit, classification=choice, support_probability=support,
        relevance_score=support + .4 * probabilities["related"],
        supported=choice == "supports" and support >= .6,
    )


def rerank_search(
    db_path: Path,
    query: str,
    *,
    provider: Any = None,
    k: int = 10,
    private: bool = True,
    evaluate: bool = False,
    cache_path: Path | None = None,
) -> RerankResult:
    """Search locally, optionally classify at most 20 hits with Jev.

    `evaluate=False` is fully offline.  A private Vercel provider is verified
    with a synthetic ZDR canary only when an uncached request is needed.  A
    failed evaluation returns the original local ranking, explicitly marked
    unassessed, rather than a partial or fabricated Jev ranking.
    """
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    if k < 0:
        raise ValueError("k must be nonnegative")
    db_path = Path(db_path).resolve()
    local = search(db_path, query, limit=min(k, MAX_RERANK_K))
    vault_root = _vault_root(db_path)
    indexed = [(hit, get_note(db_path, hit.id)) for hit in local]
    sourced = [(_local_hit(hit, note, vault_root), note) for hit, note in indexed if note is not None]
    hits = tuple(hit for hit, _ in sourced)
    if not hits:
        return RerankResult(query, (), "local", "abstain", 0, 0)
    if not evaluate:
        return RerankResult(query, hits, "local", "unassessed", 0, 0)

    cache_path = Path(cache_path).resolve() if cache_path is not None else db_path.with_name("rerank.sqlite")
    if cache_path.is_relative_to(vault_root):
        raise ValueError("Put the rerank cache outside the vault")
    evaluated = cache_hits = 0
    judged: list[RerankHit] = []
    try:
        with closing(_open_cache(cache_path)) as cache:
            for hit, note in sourced:
                key = _cache_key(query, note.content_hash, private=private)
                judgment = _read_cached(cache, key)
                if judgment is None:
                    if provider is None:
                        provider = VercelJevProvider()
                    if private and isinstance(provider, VercelJevProvider) and not provider.private_route_verified:
                        provider.verify_private_route()
                    state = {"query": query[:MAX_QUERY_CHARS], "note_excerpt": _evidence_excerpt(note.content, query)}
                    response = provider.evaluate(state, _QUESTION, private=private)
                    judgment = _validate_judgment(response.answers["relevance"])
                    _write_cached(cache, key, *judgment)
                    evaluated += 1
                else:
                    cache_hits += 1
                judged.append(_assessed(hit, judgment))
    except Exception as exc:
        return RerankResult(query, hits, "fallback", "unassessed", evaluated, cache_hits, type(exc).__name__)
    judged.sort(key=lambda hit: (hit.relevance_score or 0, hit.local_score), reverse=True)
    status = "supported" if any(hit.supported for hit in judged) else "abstain"
    return RerankResult(query, tuple(judged), "jev", status, evaluated, cache_hits)
