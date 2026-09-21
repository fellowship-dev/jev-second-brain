# Jev Second Brain

An MIT licensed, local first CLI for a Markdown or Obsidian vault. It builds a
searchable index, finds a bounded set of notes related to a new note, and can
ask [Jev](https://docs.typesafe.ai/) to judge those pairs. Every result points
back to a source path. Suggested relationships wait for human review; the CLI
does not edit source notes.

This is an MVP. The code is free; optional calls through Vercel AI Gateway use
your own key and may incur charges. A key is not needed for indexing, search,
or candidate previews.

## Install

The current pre-release is installable directly from GitHub. It is not on PyPI
and does not have a release tag yet.

```sh
pipx install "git+https://github.com/fellowship-dev/jev-second-brain.git"
secondbrain --version
```

Without `pipx`, install into your active Python environment:

```sh
python3 -m pip install "git+https://github.com/fellowship-dev/jev-second-brain.git"
```

## Try it with fictional notes

The fictional vault is kept in the source repository, so clone it for this
walkthrough. Requires Python 3.11 or newer.

```sh
git clone https://github.com/fellowship-dev/jev-second-brain.git
cd jev-second-brain
state_dir="$(mktemp -d)"
secondbrain init examples/synthetic-vault --state "$state_dir" --json
secondbrain index --state "$state_dir" --json
secondbrain search "Aurora onboarding" --state "$state_dir" --json
secondbrain suggest projects/aurora.md --state "$state_dir" --k 10 --json
```

`init` keeps SQLite and configuration in `state_dir`, outside the vault. `index`
reads Markdown files and updates the derived SQLite/FTS index. `search` returns
local matches and excerpts. `suggest` shows the candidate pool, selection
reasons, and any truncation before a model call. Its `pending_count` tells you
how many shortlisted pairs lack a cached judgment; it does not make proposals
until `--evaluate` is supplied. These commands send no note content to Jev.

For your own vault, replace `examples/synthetic-vault` with its directory.
After adding or changing a note, rerun `index`, then `suggest` with that note's
vault relative path or indexed ID. The source vault remains the authority.

## Optional Jev judgments

Set `AI_GATEWAY_API_KEY` in your environment using your normal secret manager.
Do not paste it into a command or commit it. Start with the synthetic vault:

```sh
secondbrain suggest projects/aurora.md --state "$state_dir" --k 10 --evaluate --public --max-requests 12 --max-cost-usd 0.10 --json
secondbrain search "What is planned for Aurora onboarding?" --state "$state_dir" --rerank --public --max-requests 12 --max-cost-usd 0.10 --json
```

`--public` is for material you know is non private, such as the included
fictional notes. Omit it for private material. Then the CLI runs a synthetic
canary before the first uncached pair and requires evidence that the request
used Vercel's zero data retention route to TypeSafe. If that evidence is absent,
the private evaluation stops. Vercel currently makes per request ZDR available
on Pro and Enterprise plans; check your account and the
[provider policy](docs/PRIVACY.md) before a private pilot. A private-mode run
against the fictional vault passed that gate; see the
[live canary receipt](docs/LIVE-CANARY.md). That receipt does not authorize or
validate a private-vault pilot.

`suggest --evaluate` asks Jev to classify each shortlisted pair as duplicate,
related, revises, contradicts, none, or unsure. It returns probabilities,
source and target paths, content revisions, proposal IDs, cache hits, and call
counts. It does not decide that a proposal is true. Record a decision using an
ID from the `proposals` output:

```sh
secondbrain review PROPOSAL_ID keep --state "$state_dir" --note "Checked both source notes" --json
```

`review` appends a local disposition (`keep`, `reject`, or `unsure`) to
`reviews.jsonl`. It does not add a Markdown link. A changed source or target
revision produces a new proposal ID; review the new evidence separately.

`search --rerank` first retrieves local matches, then asks Jev whether each
bounded query/note excerpt supports the question. It returns source paths,
probabilities, and `answer_status`. On a provider error, it returns the local
ranking with `mode: fallback` and an unassessed status. It does not compose an
answer or claim that an unassessed hit supports one.

Before either provider-backed command evaluates note text, it verifies the
selected files against their indexed content hashes. If a file changed,
disappeared, escaped the vault, or became a symlink after `index`, the command
fails closed and asks you to rerun `secondbrain index`. It does not send stale
indexed text to the provider.

## What is here

- Local Markdown scanning, stable note IDs, explicit link extraction, SQLite
  full text search, and a shortlist capped by `suggest --k` (1 to 50).
- Optional Jev pair judgments and search reranking, with typed answers,
  revision keyed caches, per run request/cost limits, and source paths.
- An append only local review log and the copied
  [link-new-material skill](skills/link-new-material/SKILL.md). Its origin and
  manual sync check are recorded in [provenance](skills/PROVENANCE.md).

The index holds full Markdown text locally. Model calls transmit only the
selected note pair or query/excerpt, never the entire vault. See
[privacy and data flow](docs/PRIVACY.md), [delivery phases](docs/MVP.md), and
[MVP verification](docs/RECEIPT.md) for the checks run so far. The
[live alignment benchmark](benchmarks/LIVE.md) records both the primary fixture
and an independent holdout. Those fixtures are tiny, public, synthetic, and
subject to live model variation. See `secondbrain --help` for current behavior.
Clustering, automatic tagging, deduplication actions, source writeback, and a
measured private vault pilot are later work.

## Development

```sh
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 scripts/check_skill_sync.py
```

Tests and examples use fictional notes. Contributions should keep source
Markdown untouched by default, preserve a useful offline path, and test recall
and false links separately. See [MVP phases](docs/MVP.md) for the next gates.

License: [MIT](LICENSE).
