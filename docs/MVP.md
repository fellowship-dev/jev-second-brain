# MVP phases and next gates

The first journey is deliberately narrow: index a Markdown vault, find a new
note's candidate neighbors locally, optionally classify those pairs with Jev,
review proposed links, and search the original notes with source paths. The
machine is the **incremental corpus alignment** pattern:

```text
new note + eligible corpus
    → bounded local candidate pool
    → directed pair judgments
    → relationship proposals + coverage receipt
    → human disposition
```

Candidate recall and judgment quality are separate measurements. A model
cannot recover a true neighbor absent from the shortlist. The MVP exposes
`eligible_count`, `pool_count`, `returned_count`, and `truncated_count` for
that reason.

| Phase | Deliverable | Status and verification |
| --- | --- | --- |
| 0. Package and pattern | MIT Python package, CLI entry point, fictional vault, copied `link-new-material` skill and provenance check. | **Delivered.** The GitHub install, CLI help, package build and skill sync check pass. |
| 1. Local corpus | Markdown scan, SQLite/FTS search, explicit links, stable IDs and a bounded candidate union. | **Delivered.** Tests cover add, change, rename, removal and repeat scans. Local search works without a key. |
| 2. Jev judgments | Typed Vercel evaluation adapter, privacy route canary, per run limits, revision keyed caches and directed proposals. | **Delivered for fictional data.** Mocked failure tests pass and a live private-mode fictional run verified ZDR evidence and exclusive TypeSafe routing. See [the live canary receipt](LIVE-CANARY.md). A private corpus has not been tested. |
| 3. User journey | `init`, `index`, `search`, `suggest`, `review`, plus explicit `search --rerank`. | **Delivered.** Clean install and fictional end-to-end smoke pass. Source files remain unchanged. Provider failure falls back to local search. Provider-backed commands reject an index whose selected source hashes no longer match disk and ask the user to rerun `index`. |

The code for these phases is present; verification receipts belong in the
release process rather than being inferred from this table. `README.md` shows
the runnable no key path. `docs/PRIVACY.md` describes the gate before using
private notes.

## Boundaries of this MVP

- It reads `.md` files from one directory tree. It is not yet a general
  connector system for every note app or an inbox ingestion service.
- It indexes full text locally, but Jev sees only a bounded note pair or
  query/excerpt on an explicit model command.
- Search returns source linked hits and support judgments, not a generated
  answer. Relationship proposals and human review records do not rewrite notes.
- The shortlist is not exhaustive, and scores are not calibrated correctness
  probabilities. Show no link and unsure outcomes rather than forcing a link.
- The copied skill has a documented manual sync path; no bidirectional sync
  or plugin distribution exists yet.

## Next deliverable phases

| Phase | Deliverable | Done when |
| --- | --- | --- |
| 4. Synthetic release gate | Clean package install, CI, private route canary on fictional data, and frozen evaluation sets. | **Delivered.** Ubuntu Python 3.11/3.12, macOS 3.12, and Windows 3.12 CI passed. Live fictional canaries, candidate recall, mocked rerank behavior, and primary plus holdout live alignment are recorded. The holdout improved from 10/12 to 12/12 exact and acceptable after rubric clarification. |
| 5. Private pilot | Opt in 300 to 500 note sample with source permissions, baseline searches, human review time, and measured retrieval quality. | Owner has reviewed data handling and pilot scope; no automatic source edits; before/after metrics include misses and wrong links. |
| 6. Broader second brain | Pre tags, buckets, clusters, duplicate review, cross links, portable adapters, and optional reviewed writeback. | Each action has an explainable preview, reversible provenance, a quality benchmark, and a documented authority boundary. |
| 7. Public distribution | Public standalone repository, versioned package/skill, contribution guidance and repeatable releases. | **In progress.** The repository and Git install are public. A tag, GitHub release, package-registry release and release automation remain. |

Keep local recall, typed provider judgment, and human acceptance distinct in
both design and measurement. The copied pattern skill is in
[`skills/link-new-material/SKILL.md`](../skills/link-new-material/SKILL.md).
