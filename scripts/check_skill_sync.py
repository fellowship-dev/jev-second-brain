"""Check the copied pattern skill against its provenance and optional source."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "link-new-material" / "SKILL.md"
PROVENANCE = ROOT / "skills" / "PROVENANCE.md"


def _digest_bytes(content: bytes) -> str:
    """Hash logical text consistently across LF and CRLF checkouts."""
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def _digest(path: Path) -> str:
    return _digest_bytes(path.read_bytes())


def _recorded_hash(provenance: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)} SHA-256: `([0-9a-f]{{64}})`$", provenance, re.MULTILINE)
    if not match:
        raise ValueError(f"missing {label} SHA-256 in provenance")
    return match.group(1)


def check(
    skill: Path,
    provenance: Path,
    source: Path | None = None,
    source_bytes: bytes | None = None,
) -> list[str]:
    """Return drift findings; no source path means local copy validation only."""
    record = provenance.read_text(encoding="utf-8")
    findings = []
    if _digest(skill) != _recorded_hash(record, "Copy"):
        findings.append("local copy changed: update provenance after reviewing adaptation")
    if source is not None and source_bytes is not None:
        raise ValueError("provide one source, as a path or bytes")
    upstream_hash = _digest(source) if source is not None else (
        _digest_bytes(source_bytes) if source_bytes is not None else None
    )
    if upstream_hash is not None and upstream_hash != _recorded_hash(record, "Source"):
        findings.append("source changed: inspect upstream changes before syncing the copy")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    upstream = parser.add_mutually_exclusive_group()
    upstream.add_argument("--source", type=Path, help="path to the upstream SKILL.md checkout")
    upstream.add_argument("--source-repo", type=Path, help="path to the upstream Git repository")
    parser.add_argument("--source-ref", default="main", help="upstream Git ref (default: main)")
    args = parser.parse_args(argv)
    try:
        source_bytes = None
        if args.source_repo is not None:
            source_path = "skills/ops/link-new-material/SKILL.md"
            source_bytes = subprocess.run(
                ["git", "-C", str(args.source_repo), "show", f"{args.source_ref}:{source_path}"],
                check=True,
                capture_output=True,
            ).stdout
        findings = check(SKILL, PROVENANCE, args.source, source_bytes)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"skill sync check failed: {error}\n")
    if findings:
        for finding in findings:
            print(finding)
        return 1
    print("local skill copy matches provenance" + (" and source" if args.source or args.source_repo else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
