"""Append-only decisions on proposed links; source Markdown is never modified."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


DISPOSITIONS = frozenset({"keep", "reject", "unsure"})


def proposal_id(
    source_id: str,
    source_revision: str,
    target_id: str,
    target_revision: str,
    relation: str,
) -> str:
    """Identify one directed, revision-specific relationship proposal."""
    fields = (source_id, source_revision, target_id, target_revision, relation)
    if any(not isinstance(value, str) or not value.strip() for value in fields):
        raise ValueError("proposal identity fields must be non-empty strings")
    canonical = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"link_{digest}"


def latest_reviews(state_file: str | Path) -> dict[str, dict[str, str | None]]:
    """Read latest dispositions without hiding a damaged append-only log."""
    path = Path(state_file)
    if not path.exists():
        return {}
    latest: dict[str, dict[str, str | None]] = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid review log at line {line_number}") from error
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("proposal_id"), str)
                or not record["proposal_id"]
                or record.get("disposition") not in DISPOSITIONS
                or not isinstance(record.get("reviewed_at"), str)
                or "note" not in record
                or (record.get("note") is not None and not isinstance(record["note"], str))
            ):
                raise ValueError(f"invalid review record at line {line_number}")
            latest[record["proposal_id"]] = record
    return latest


def append_review(
    state_file: str | Path,
    *,
    proposal_id: str,
    disposition: str,
    note: str | None = None,
) -> dict[str, str | None]:
    """Record keep/reject/unsure; an identical current decision is a no-op.

    The caller supplies an explicit state path outside its source vault. A
    correction adds an event, preserving the previous human decision.
    """
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        raise ValueError("proposal_id must be a non-empty string")
    if disposition not in DISPOSITIONS:
        raise ValueError("disposition must be keep, reject, or unsure")
    if note is not None and not isinstance(note, str):
        raise ValueError("note must be a string or None")
    path = Path(state_file)
    previous = latest_reviews(path).get(proposal_id)
    if previous and previous["disposition"] == disposition and previous["note"] == note:
        return previous
    record: dict[str, str | None] = {
        "proposal_id": proposal_id,
        "disposition": disposition,
        "note": note,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return record
