# Live Jev canary receipt

This receipt proves that the provider path worked on the repository's
fictional vault. It does not prove relationship quality on a real corpus and
does not authorize sending private notes.

## Scope

- Input: the five fictional Markdown notes under `examples/synthetic-vault`.
- Mode: private mode, which is the default when `--public` is absent.
- Route policy: `zeroDataRetention: true`, model `typesafe-ai/jev`, and the
  TypeSafe-only provider allowlist.
- Local limits: 12 request attempts and $0.10 reported cost for each command.
- Secret handling: `AI_GATEWAY_API_KEY` was read from the environment and was
  not written to the receipt, cache, command output, or repository.

## Relationship run

Starting from a new external state directory, the measured command was:

```sh
secondbrain init examples/synthetic-vault --state "$state_dir" --json
secondbrain index --state "$state_dir" --json
secondbrain suggest projects/aurora.md --state "$state_dir" --k 10 --evaluate --max-requests 12 --max-cost-usd 0.10 --json
```

The synthetic canary returned the required ZDR evidence, and route metadata
showed exclusive `typesafe-ai` execution. Only then did the command send the
three fictional note pairs. Their top relations were `related`, `related`, and
`none`.

Aggregate provider usage across the canary and the three pair calls:

| Field | Value |
| --- | ---: |
| Requests | 4 |
| Request bytes | 4,999 |
| Input tokens | 2,683 |
| Output tokens | 213 |
| Reported cost | $0 |

After removing the key from the environment, repeating the same `suggest`
command returned three cache hits, zero pending pairs, and zero provider calls.
This verifies the unchanged-input replay path without assuming that a cached
model judgment is a human-accepted link.

## Search rerank run

The measured query was:

```sh
secondbrain search "What is planned for Aurora onboarding?" --state "$state_dir" --rerank --max-requests 12 --max-cost-usd 0.10 --json
```

Three fictional search hits were evaluated. Their top classifications were
`supports`, `related`, and `irrelevant`; support probabilities were 0.70, 0.01,
and 0.00. The result mode was `jev` and its answer status was `supported`.

Aggregate provider usage across the canary and three note calls:

| Field | Value |
| --- | ---: |
| Requests | 4 |
| Request bytes | 2,596 |
| Input tokens | 1,592 |
| Output tokens | 149 |
| Reported cost | $0 |

Repeating the query without a key returned three cache hits, evaluated zero
notes, and made zero provider calls.

## Live alignment benchmark

The public benchmark harness evaluates fixed source/target pairs directly, so
it measures live classification separately from local candidate recall.

The six-case primary fixture
`a6f5d73dddf70bc40249cbf489d1ac3361283c0e11fd6637d8e1e872a56f8707`
stayed at 5/6 exact and acceptable after the rubric update. One disputed
related/paraphrase pair received raw top choice `duplicate` with probability
0.55. The shipped 0.65 threshold converted that weak result to `unsure`,
preferring abstention over an unsupported duplicate link.

The independent 12-case holdout
`87a22df434ffc3902e23b4a0256b4692e4f7d0cee53f5b38a6376d45ba7313b5`
improved from 10/12 to 12/12 exact and acceptable after revision direction and
authority/chronology rules became explicit. Abstention recall improved from
1/2 to 2/2.

| Fixture | Requests | Request bytes | Input tokens | Output tokens | Reported cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary, 6 cases | 6 | 12,865 | 4,302 | 389 | $0 |
| Holdout, 12 cases | 12 | 25,732 | 8,673 | 775 | $0 |

Both fixtures are tiny, public, and synthetic. Live model results can vary;
these values describe the recorded runs. See
[`benchmarks/LIVE.md`](../benchmarks/LIVE.md) for the harness and commands.

## Stale-index preflight

Provider-backed relationship and rerank commands compare selected files with
their indexed hashes before evaluation. When a selected source changed,
disappeared, escaped the vault, or became a symlink, the command fails closed
and asks the user to run `index` and retry. Hash-mismatch regression tests make
zero provider calls. This prevents an old index or cache identity from silently
standing in for the current file.

## What this establishes

- Private-mode fictional requests fail closed until the route canary passes.
- The measured canary produced ZDR evidence and an exclusive TypeSafe route.
- Relationship and rerank cache replays can complete without a key or provider
  call when the query, note revisions, rubric, model, and privacy mode match.
- The provider's reported cost for both measured first runs was zero. These are
  two receipts, not a promise of free future inference.
- The live alignment rubric produced a perfect result on the independent
  12-case holdout while preserving a conservative abstention on the disputed
  primary pair.

The next quality gate is a separately scoped private pilot that measures
candidate recall, wrong links, abstentions, and human review time on authorized
notes without enabling automatic source edits.
