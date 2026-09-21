# Contributing

Jev Second Brain is an early local-first CLI. Small, reviewable changes with
fictional fixtures are easiest to evaluate.

## Set up

Requires Python 3.11 or newer.

```sh
git clone https://github.com/fellowship-dev/jev-second-brain.git
cd jev-second-brain
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 scripts/check_skill_sync.py
```

Run the fictional local journey from `README.md` when changing the CLI, index,
candidate discovery, or packaging. Provider tests should use fakes. Do not make
a live model call from an automated test.

## Choose an issue

Bug reports and narrowly scoped proposals are welcome. For a larger adapter,
storage change, or source-writing feature, open an issue first with the user
outcome, data boundary, and verification plan. An issue labeled
`good first issue` should include the relevant files, expected behavior, and a
clear acceptance check.

## Project boundaries

- Markdown is authoritative. Indexes, caches, proposals, and review logs are
  derived state.
- Local search must remain useful without a provider key.
- Provider calls must be explicit, bounded, typed, and source linked.
- A model proposal is not a fact or a human decision.
- Source changes require a preview, explicit authority, and an idempotent path.
- Measure candidate recall separately from final relationship quality.

## Privacy

Use only the fictional fixtures or data you created for a test. Never commit a
real vault, private note text, provider prompt/response containing private
content, API key, state directory, SQLite database, or captured private CLI
output. Redact bug reports and test fixtures before sharing them.

Report vulnerabilities through the process in [SECURITY.md](SECURITY.md), not
a public issue containing exploit or private-data details.

## Pull requests

Keep each pull request focused. Include:

- the user-visible change and why it is needed;
- commands and results used to verify it;
- any provider calls, request limits, and data sent;
- documentation updates for changed commands, privacy, or release behavior;
- fictional regression coverage for bugs and judgment edge cases.

The project uses the MIT license. By contributing, you agree that your
contribution is licensed under it.
