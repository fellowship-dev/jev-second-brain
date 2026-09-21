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

| Phase | Deliverable | Verification |
| --- | --- | --- |
| 0. Package and pattern | MIT Python package, CLI entry point, fictional vault, copied `link-new-material` skill and provenance check. | Install locally; CLI help and skill sync check pass. |
| 1. Local corpus | Markdown scan, SQLite/FTS search, explicit links, stable IDs and a bounded candidate union. | Add, change, rename, remove and repeat scans against fictional notes; local search remains usable without a key. |
| 2. Jev judgments | Typed Vercel evaluation adapter, privacy route canary, per run limits, revision keyed caches and directed proposals. | Mocked provider tests cover cache replay, no link, uncertainty, changed revisions, transport and policy failures. A live synthetic canary is still needed before claiming a working account route. |
| 3. User journey | `init`, `index`, `search`, `suggest`, `review`, plus explicit `search --rerank`. | Install in a clean environment and run the fictional vault smoke path. Source files remain unchanged. Reranking without a provider falls back to local matches. |

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
| 4. Synthetic release gate | Clean package install, cross platform CI, private route canary on fictional data, and a frozen small corpus evaluation set. | Source preserving end to end run is captured, including request count, cost, candidate recall, false links and abstentions. |
| 5. Private pilot | Opt in 300 to 500 note sample with source permissions, baseline searches, human review time, and measured retrieval quality. | Owner has reviewed data handling and pilot scope; no automatic source edits; before/after metrics include misses and wrong links. |
| 6. Broader second brain | Pre tags, buckets, clusters, duplicate review, cross links, portable adapters, and optional reviewed writeback. | Each action has an explainable preview, reversible provenance, a quality benchmark, and a documented authority boundary. |
| 7. Public distribution | Publish a standalone GitHub repository and versioned package/skill, with contribution guidance and repeatable releases. | Owner approves publication after secret and private data audit; install and release artifacts match the tested commit. |

Keep local recall, typed provider judgment, and human acceptance distinct in
both design and measurement. The copied pattern skill is in
[`skills/link-new-material/SKILL.md`](../skills/link-new-material/SKILL.md).
