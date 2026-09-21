"""Derived SQLite index for a Markdown vault. Source files are never modified."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import sqlite3
import uuid


_HEADING = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)
_WIKI_LINK = re.compile(r"\[\[([^\]\n]+)\]\]")
_MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_SEARCH_WORD = re.compile(r"[^\W_]+(?:[-_][^\W_]+)*", re.UNICODE)


@dataclass(frozen=True)
class Note:
    id: str
    path: str  # relative to the indexed vault root
    title: str
    content: str
    content_hash: str


@dataclass(frozen=True)
class SearchHit:
    id: str
    path: str
    title: str
    excerpt: str
    score: float


@dataclass(frozen=True)
class ScanReport:
    total: int
    added: int
    changed: int
    renamed: int
    unchanged: int
    tombstoned: int


def _connect(db_path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS notes_active_path_idx ON notes(path) WHERE deleted=0;
        CREATE INDEX IF NOT EXISTS notes_hash_idx ON notes(content_hash);
        CREATE TABLE IF NOT EXISTS links (
            source_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            target TEXT NOT NULL,
            PRIMARY KEY (source_id, target)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
            id UNINDEXED, title, content, tokenize='unicode61'
        );
        """
    )


def _title(path: Path, content: str) -> str:
    # A YAML block at the very top is metadata, not a Markdown heading.
    body = content
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end >= 0:
            body = body[end + 5 :]
    heading = _HEADING.search(body)
    return heading.group(1).strip() if heading else path.stem


def _links(content: str) -> set[str]:
    links = {match.group(1).split("|", 1)[0].strip() for match in _WIKI_LINK.finditer(content)}
    links.update(match.group(1).strip() for match in _MARKDOWN_LINK.finditer(content))
    return {link for link in links if link and not re.match(r"[a-z][a-z\d+.-]*:", link, re.I)}


def _read_source(vault: Path) -> dict[str, tuple[str, str, str, set[str]]]:
    if not vault.is_dir():
        raise ValueError(f"Vault is not a directory: {vault}")
    documents: dict[str, tuple[str, str, str, set[str]]] = {}
    for source in sorted(vault.rglob("*")):
        if source.suffix.casefold() != ".md" or ".git" in source.relative_to(vault).parts:
            continue
        if source.is_symlink():
            raise ValueError(f"Markdown symlink requires review: {source}")
        if not source.is_file():
            continue
        relative = source.relative_to(vault).as_posix()
        content = source.read_text(encoding="utf-8")  # strict: failed scan leaves prior index intact
        documents[relative] = (_title(source, content), content, sha256(content.encode()).hexdigest(), _links(content))
    return documents


def scan_and_index(vault: Path, db_path: Path) -> ScanReport:
    """Atomically update the derived index after a complete, successful scan.

    A same-path edit retains its ID. A content-identical rename retains its ID
    only when the old and new unmatched hashes are each unique. Removed notes
    become tombstones, retaining their IDs but leaving search and link results.
    """
    vault = Path(vault).resolve()
    db_path = Path(db_path).resolve()
    if db_path.is_relative_to(vault):
        raise ValueError("Put the SQLite index outside the vault")
    documents = _read_source(vault)
    connection = _connect(db_path)
    try:
        _schema(connection)
        old_vault_row = connection.execute("SELECT value FROM metadata WHERE key='vault'").fetchone()
        if old_vault_row and old_vault_row["value"] != str(vault):
            raise ValueError("Index already belongs to a different vault")
        old = {row["path"]: row for row in connection.execute("SELECT * FROM notes WHERE deleted=0")}
        unmatched_old = {path: row for path, row in old.items() if path not in documents}
        unmatched_new = {path: doc for path, doc in documents.items() if path not in old}
        old_hashes: dict[str, list[sqlite3.Row]] = {}
        new_hashes: dict[str, list[str]] = {}
        for row in unmatched_old.values():
            old_hashes.setdefault(row["content_hash"], []).append(row)
        for path, doc in unmatched_new.items():
            new_hashes.setdefault(doc[2], []).append(path)
        renamed: dict[str, sqlite3.Row] = {}
        for digest, paths in new_hashes.items():
            prior = old_hashes.get(digest, [])
            if len(paths) == len(prior) == 1:
                renamed[paths[0]] = prior[0]

        added = changed = unchanged = 0
        with connection:
            connection.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('vault',?)", (str(vault),))
            # A removed path might be occupied by a rename in this same scan.
            for row in unmatched_old.values():
                connection.execute("UPDATE notes SET deleted=1 WHERE id=?", (row["id"],))
            for path, (title, content, digest, links) in documents.items():
                prior = old.get(path) or renamed.get(path)
                if prior:
                    note_id = prior["id"]
                    if path in old and old[path]["content_hash"] == digest and old[path]["title"] == title:
                        unchanged += 1
                    elif path in old:
                        changed += 1
                    connection.execute(
                        "UPDATE notes SET path=?,title=?,content=?,content_hash=?,deleted=0 WHERE id=?",
                        (path, title, content, digest, note_id),
                    )
                else:
                    note_id = uuid.uuid4().hex
                    connection.execute(
                        "INSERT INTO notes(id,path,title,content,content_hash) VALUES(?,?,?,?,?)",
                        (note_id, path, title, content, digest),
                    )
                    added += 1
                connection.execute("DELETE FROM links WHERE source_id=?", (note_id,))
                connection.executemany("INSERT INTO links(source_id,target) VALUES(?,?)", ((note_id, link) for link in links))
            connection.execute("DELETE FROM notes_fts")
            connection.execute(
                "INSERT INTO notes_fts(id,title,content) SELECT id,title,content FROM notes WHERE deleted=0"
            )
        return ScanReport(
            total=len(documents), added=added, changed=changed, renamed=len(renamed),
            unchanged=unchanged, tombstoned=len(unmatched_old) - len(renamed),
        )
    finally:
        connection.close()


def list_notes(db_path: Path, *, include_deleted: bool = False) -> list[Note]:
    with closing(_connect(Path(db_path), read_only=True)) as connection:
        rows = connection.execute(
            "SELECT id,path,title,content,content_hash FROM notes"
            + ("" if include_deleted else " WHERE deleted=0") + " ORDER BY path"
        ).fetchall()
    return [Note(**dict(row)) for row in rows]


def get_note(db_path: Path, note_id: str) -> Note | None:
    with closing(_connect(Path(db_path), read_only=True)) as connection:
        row = connection.execute(
            "SELECT id,path,title,content,content_hash FROM notes WHERE id=? AND deleted=0", (note_id,)
        ).fetchone()
    return Note(**dict(row)) if row else None


def require_fresh_source(vault: Path, note: Note) -> Path:
    """Fail closed when an indexed note no longer matches its source file."""
    vault = Path(vault).resolve()
    source = vault / note.path
    if source.is_symlink():
        raise ValueError(f"Indexed source became a symlink; run index and retry: {note.path}")
    resolved = source.resolve()
    if not resolved.is_relative_to(vault) or not resolved.is_file():
        raise ValueError(f"Indexed source is missing or escapes the vault; run index and retry: {note.path}")
    content = resolved.read_text(encoding="utf-8")
    if sha256(content.encode()).hexdigest() != note.content_hash:
        raise ValueError(f"Indexed source changed; run index and retry: {note.path}")
    return resolved


def search(db_path: Path, query: str, limit: int = 20) -> list[SearchHit]:
    """Local full-text retrieval; returns source paths and snippets, no provider call."""
    if limit <= 0:
        return []
    words = _SEARCH_WORD.findall(query)
    if not words:
        return []
    fts_query = " OR ".join('"' + word.replace('"', '""') + '"' for word in words[:16])
    with closing(_connect(Path(db_path), read_only=True)) as connection:
        rows = connection.execute(
            """SELECT n.id,n.path,n.title,
                      snippet(notes_fts,2,'[',']',' … ',18) AS excerpt,
                      bm25(notes_fts,4.0,1.0) AS rank
               FROM notes_fts JOIN notes n ON n.id=notes_fts.id
               WHERE notes_fts MATCH ? AND n.deleted=0 ORDER BY rank LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
    return [SearchHit(row["id"], row["path"], row["title"], row["excerpt"], -row["rank"]) for row in rows]
