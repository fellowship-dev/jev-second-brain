"""Command-line entry point for the standalone package."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import sys

from . import __version__
from .alignment import suggest_for_note
from .config import init_project, load_config
from .index import list_notes, scan_and_index, search
from .policy import BudgetLimits, PolicyError
from .provider import ProviderError, VercelJevProvider
from .rerank import rerank_search
from .reviews import append_review, latest_reviews


def _emit(payload: dict, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def _provider_usage(provider: VercelJevProvider) -> dict[str, int | str]:
    """Report the whole provider session, including canary and retries."""
    budget = provider.budget
    return {
        "requests": budget.requests,
        "request_bytes": budget.request_bytes,
        "input_tokens": budget.input_tokens,
        "output_tokens": budget.output_tokens,
        "cost_usd": str(budget.cost_usd),
    }


def _state_command(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state", required=True, type=Path, help="Project state directory created by init")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")


def _evaluation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evaluate", action="store_true", help="Send bounded candidates to Jev")
    parser.add_argument("--public", action="store_true", help="Treat source as non-private; skip private route canary")
    parser.add_argument("--max-requests", type=int, default=25, help="Maximum Gateway attempts including canary")
    parser.add_argument("--max-cost-usd", type=Decimal, default=Decimal("1"))


class _LazyPrivateProvider(VercelJevProvider):
    def evaluate(self, state, questions, *, private=True):
        if private and not self.private_route_verified:
            self.verify_private_route()
        return super().evaluate(state, questions, private=private)


def _note_id(db_path: Path, vault: Path, selector: str) -> str:
    notes = list_notes(db_path)
    by_id = next((note for note in notes if note.id == selector), None)
    if by_id:
        return by_id.id
    candidate = Path(selector)
    if candidate.is_absolute():
        try:
            selector = candidate.resolve().relative_to(vault).as_posix()
        except ValueError as exc:
            raise ValueError("Selected note is outside the configured vault") from exc
    match = next((note for note in notes if note.path == selector), None)
    if match is None:
        raise ValueError(f"Indexed note not found: {selector}")
    return match.id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="secondbrain",
        description="Local-first Markdown memory tooling",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="Configure a Markdown vault without modifying it")
    initialize.add_argument("vault", type=Path)
    initialize.add_argument("--state", type=Path, help="State directory outside the vault")
    initialize.add_argument("--json", action="store_true")
    indexing = commands.add_parser("index", help="Refresh the local index")
    _state_command(indexing)
    searching = commands.add_parser("search", help="Search indexed notes locally")
    searching.add_argument("query")
    searching.add_argument("--limit", type=int, default=10)
    searching.add_argument("--rerank", action="store_true", help="Use Jev on the bounded local shortlist")
    searching.add_argument("--public", action="store_true", help="Treat source as non-private; skip private route canary")
    searching.add_argument("--max-requests", type=int, default=25)
    searching.add_argument("--max-cost-usd", type=Decimal, default=Decimal("1"))
    _state_command(searching)
    suggesting = commands.add_parser("suggest", help="Shortlist and optionally judge links for one note")
    suggesting.add_argument("note", help="Indexed note ID or path relative to vault")
    suggesting.add_argument("--k", type=int, default=20, help="Candidate cap (1 to 50)")
    _evaluation_options(suggesting)
    _state_command(suggesting)
    reviewing = commands.add_parser("review", help="Record a disposition for a proposed relationship")
    reviewing.add_argument("proposal_id")
    reviewing.add_argument("disposition", choices=("keep", "reject", "unsure"))
    reviewing.add_argument("--note", help="Optional review rationale")
    _state_command(reviewing)
    args = parser.parse_args(argv)

    if args.command == "init":
        config = init_project(args.vault, state_dir=args.state)
        _emit({"vault": str(config.vault), "state": str(config.state_dir), "db": str(config.db_path)}, json_output=args.json)
    elif args.command == "index":
        config = load_config(args.state)
        report = scan_and_index(config.vault, config.db_path)
        _emit(asdict(report), json_output=args.json)
    elif args.command == "search":
        config = load_config(args.state)
        if args.limit < 1 or args.limit > 100:
            parser.error("--limit must be between 1 and 100")
        if args.rerank:
            if args.limit > 20:
                parser.error("--rerank limits results to at most 20")
            provider = _LazyPrivateProvider(
                limits=BudgetLimits(max_requests=args.max_requests, max_cost_usd=args.max_cost_usd)
            )
            result = rerank_search(
                config.db_path,
                args.query,
                provider=provider,
                k=args.limit,
                private=not args.public,
                evaluate=True,
                cache_path=config.state_dir / "rerank-cache.sqlite",
            )
            _emit({**asdict(result), "provider_usage": _provider_usage(provider)}, json_output=args.json)
        else:
            hits = search(config.db_path, args.query, args.limit)
            _emit(
                {
                    "query": args.query,
                    "vault": str(config.vault),
                    "hits": [
                        {**asdict(hit), "source_path": str(config.vault / hit.path)}
                        for hit in hits
                    ],
                },
                json_output=args.json,
            )
    elif args.command == "suggest":
        config = load_config(args.state)
        try:
            provider = (
                _LazyPrivateProvider(limits=BudgetLimits(max_requests=args.max_requests, max_cost_usd=args.max_cost_usd))
                if args.evaluate else None
            )
            result = suggest_for_note(
                config.db_path,
                _note_id(config.db_path, config.vault, args.note),
                k=args.k,
                provider=provider,
                cache_path=config.state_dir / "alignment-cache.sqlite",
                private=not args.public,
                evaluate=args.evaluate,
            )
        except (PolicyError, ProviderError, ValueError) as exc:
            print(f"secondbrain: {exc}", file=sys.stderr)
            return 2
        payload = asdict(result)
        if provider is not None:
            payload["provider_usage"] = _provider_usage(provider)
        reviews = latest_reviews(config.state_dir / "reviews.jsonl")
        for proposal in payload["proposals"]:
            proposal["review"] = reviews.get(proposal["proposal_id"])
        _emit({**payload, "vault": str(config.vault)}, json_output=args.json)
    elif args.command == "review":
        config = load_config(args.state)
        record = append_review(
            config.state_dir / "reviews.jsonl",
            proposal_id=args.proposal_id,
            disposition=args.disposition,
            note=args.note,
        )
        _emit(record, json_output=args.json)
    return 0
