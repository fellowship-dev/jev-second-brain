"""Bounded local candidate generation for incremental corpus alignment."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import PurePosixPath, Path
import re
from urllib.parse import unquote

from .index import Note, _connect, list_notes, search


_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset({
    "a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to",
    "with", "notes", "note", "readme", "index", "project", "meeting", "update", "status",
})
_LEXICAL_DICE_FLOOR = 0.30
_TITLE_DICE_FLOOR = 0.80


@dataclass(frozen=True)
class Candidate:
    note_id: str
    path: str
    title: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CandidateSet:
    source_id: str
    eligible_count: int
    pool_count: int
    returned_count: int
    truncated_count: int
    candidates: tuple[Candidate, ...]


def _words(text: str) -> set[str]:
    return {word.casefold() for word in _WORD.findall(text) if len(word) > 2 and word.casefold() not in _STOP}


def _dice(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return 2 * len(left & right) / (len(left) + len(right))


def _ordered_words(text: str) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for match in _WORD.finditer(text):
        word = match.group().casefold()
        if len(word) > 2 and word not in _STOP and word not in seen:
            seen.add(word)
            ordered.append(word)
    return ordered


def _resolve_target(raw: str, source: Note, by_path: dict[str, Note], by_stem: dict[str, list[Note]]) -> Note | None:
    target = unquote(raw.split("#", 1)[0].strip()).replace("\\", "/")
    if not target:
        return None
    target = target.lstrip("/")
    source_folder = PurePosixPath(source.path).parent
    candidates = [target, str(source_folder / target)]
    for value in candidates:
        parts: list[str] = []
        for part in PurePosixPath(value).parts:
            if part == "..":
                if parts:
                    parts.pop()
            elif part not in (".", "/"):
                parts.append(part)
        normalized = "/".join(parts)
        for path in (normalized, normalized + ".md"):
            note = by_path.get(path.casefold())
            if note:
                return note
    # Obsidian basename links are safe only when there is one matching note.
    stem = PurePosixPath(target).stem.casefold()
    matches = by_stem.get(stem, [])
    return matches[0] if len(matches) == 1 else None


def candidates_for_note(db_path: Path, note_id: str, k: int = 20) -> CandidateSet:
    """Union exact links, identical content, title overlap and FTS; cap at *k*.

    Reasons and truncation counts make shortlist coverage inspectable before any
    Jev call. Only live notes are eligible; model judgments are intentionally
    absent from this stage.
    """
    if k < 1:
        raise ValueError("k must be positive")
    notes = list_notes(db_path)
    by_id = {note.id: note for note in notes}
    source = by_id.get(note_id)
    if source is None:
        raise ValueError(f"Unknown active note id: {note_id}")
    by_path = {note.path.casefold(): note for note in notes}
    by_stem: dict[str, list[Note]] = {}
    for note in notes:
        by_stem.setdefault(PurePosixPath(note.path).stem.casefold(), []).append(note)
    signals: dict[str, dict[str, float]] = {}

    def add(other_id: str, reason: str, weight: float) -> None:
        if other_id != note_id and other_id in by_id:
            signals.setdefault(other_id, {})[reason] = max(weight, signals.get(other_id, {}).get(reason, 0))

    with closing(_connect(Path(db_path), read_only=True)) as connection:
        links = connection.execute("SELECT source_id,target FROM links").fetchall()
    for link in links:
        link_source = by_id.get(link["source_id"])
        if link_source is None:
            continue
        target = _resolve_target(link["target"], link_source, by_path, by_stem)
        if target is None:
            continue
        if link_source.id == note_id:
            add(target.id, "outgoing_link", 100.0)
        elif target.id == note_id:
            add(link_source.id, "incoming_link", 95.0)

    source_title_words = _words(source.title)
    source_words = _words(source.title + " " + source.content[:2_000])
    lexical_evidence: dict[str, tuple[float, float]] = {}
    for note in notes:
        if note.id == note_id:
            continue
        if note.content_hash == source.content_hash:
            add(note.id, "same_content", 90.0)
        title_dice = _dice(source_title_words, _words(note.title))
        lexical_dice = _dice(source_words, _words(note.title + " " + note.content[:2_000]))
        lexical_evidence[note.id] = (title_dice, lexical_dice)
        # A partial title collision is weak on its own (for example, the same
        # project word attached to unrelated subjects). Admit lexical candidates
        # only when the whole title is nearly identical or content corroborates
        # it. Exact links and byte-identical content bypass this precision gate.
        if title_dice >= _TITLE_DICE_FLOOR or lexical_dice >= _LEXICAL_DICE_FLOOR:
            if title_dice > 0:
                add(note.id, "title_overlap", 10.0 + title_dice * 10.0)
            add(note.id, "lexical_overlap", 20.0 + lexical_dice * 40.0)

    # Search title and a bounded body prefix so differently named notes can
    # still meet in the local shortlist. The final pair cap remains k.
    query_terms = _ordered_words(source.title + " " + source.content[:2_000])[:16]
    hits = [
        hit for hit in search(db_path, " ".join(query_terms), limit=max(30, k * 5))
        if hit.id != note_id
    ]
    best_score = max((hit.score for hit in hits), default=0.0)
    for hit in hits:
        title_dice, lexical_dice = lexical_evidence.get(hit.id, (0.0, 0.0))
        if title_dice < _TITLE_DICE_FLOOR and lexical_dice < _LEXICAL_DICE_FLOOR:
            continue
        relative_score = hit.score / best_score if best_score > 0 else 0.0
        add(hit.id, "full_text", 10.0 + relative_score * 30.0)

    ranked = sorted(
        (
            Candidate(
                note_id=other_id,
                path=by_id[other_id].path,
                title=by_id[other_id].title,
                score=max(reason_weights.values()) + len(reason_weights) - 1,
                reasons=tuple(sorted(reason_weights, key=lambda reason: -reason_weights[reason])),
            )
            for other_id, reason_weights in signals.items()
        ),
        key=lambda candidate: (-candidate.score, candidate.path.casefold(), candidate.note_id),
    )
    return CandidateSet(
        source_id=note_id,
        eligible_count=len(notes) - 1,
        pool_count=len(ranked),
        returned_count=min(k, len(ranked)),
        truncated_count=max(0, len(ranked) - k),
        candidates=tuple(ranked[:k]),
    )
