# MVP delivery phases

The first user journey is: index a synthetic Markdown vault, search for source
notes, compare one new note with a bounded candidate set, and inspect proposed
links with exact source references. The user can repeat it without paying for
unchanged judgments. No command changes source Markdown in the MVP.

| Phase | Deliverable | Done when |
| --- | --- | --- |
| 0. Package and pattern | Installable MIT Python CLI, repo instructions, synthetic vault, and a copied `link-new-material` skill with provenance/sync note. | Clean install and CLI help work without a key; package contains no private data. |
| 1. Local corpus | Incremental Markdown scan, SQLite/FTS search, stable note IDs, explicit links, and bounded candidate union. | Changed and removed notes update search; unchanged replay does no provider work; synthetic candidate recall and truncation are visible. |
| 2. Jev alignment | Typed source/target judgments, explicit ZDR/provider policy, budgets, retry and durable cache; deterministic relation proposals. | Synthetic canary and fake-provider tests pass; no-link, uncertainty, asymmetric relations, revisions and provider failure are safe. |
| 3. User journey | `init`, `index`, `search`, `suggest`, and `review` CLI commands with JSON output and source paths. | Packed install and synthetic end-to-end smoke pass; read-only default and zero-call repeat are demonstrated. |

The MVP is a proof of the reusable **incremental corpus alignment** pattern:
`new note + eligible corpus → candidate shortlist → pair judgments → proposed
relations + coverage receipt`. Candidate discovery and Jev judgment are measured
separately. A later private Vault pilot and public GitHub release need separate
receipts. Reusable code is extracted only when the first real adapter proves its
interface; the copied skill documents the method from day one.
