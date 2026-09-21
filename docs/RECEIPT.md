# MVP verification receipt

Verification covers the public repository at
[`fellowship-dev/jev-second-brain`](https://github.com/fellowship-dev/jev-second-brain)
and the fictional vault committed under `examples/synthetic-vault`. No private
corpus was indexed or transmitted for these receipts.

## Package and offline journey

Verified on macOS, 2026-09-20 (America/Santiago):

| Check | Result |
| --- | --- |
| Synthetic tests | `PYTHONPATH=src python3 -m unittest discover -s tests -q`: 45 passed at the original MVP commit. |
| Integrated tests | The final launch-preparation tree passed 70 tests locally on 2026-09-21, including candidate, rerank, live-alignment, and stale-index coverage. Benchmark result claims remain separate below. |
| Skill provenance | `python3 scripts/check_skill_sync.py --source-repo ../jev-pattern-library-draft`: matched the recorded source and copy hashes. |
| Package build | The final tree built `jev_second_brain-0.1.0-py3-none-any.whl`. |
| Clean install | That wheel installed into a clean temporary virtual environment; the installed CLI completed `init`, `index`, `search`, and `suggest`. |
| Synthetic journey | 5 notes indexed; search returned 3 local hits; one-note preview returned 2 pending candidate judgments and made zero provider calls. |
| Source preservation | Synthetic fixture files were unchanged. Derived state was outside the vault. |

After publication, a clean clone from the public URL also installed and
completed the five-note local journey. The final wheel receipt above reflects
the later candidate-selection changes.

## Remote CI

[GitHub Actions run 35558779025](https://github.com/fellowship-dev/jev-second-brain/actions/runs/35558779025)
passed on 2026-09-21. Both Ubuntu Python 3.11 and 3.12 jobs completed package
install, unit tests, skill provenance validation, and the installed CLI smoke
journey. The workflow now also declares macOS 3.12 and Windows 3.12 jobs, but
that expanded matrix has not run. Cross-platform verification remains pending.

## Deterministic benchmark receipts

The frozen candidate corpus uses six expected relationships and one deliberately
undiscoverable semantic relationship. Candidate changes were compared against
the prior implementation on the same fixture:

| Metric | Before | Current |
| --- | ---: | ---: |
| Micro recall@3 | 0.833333 | 0.833333 |
| Micro recall@1 | 0.666667 | 0.833333 |
| Hard-negative intrusion rate | 1.0 | 0.0 |

The current result finds five of six expected targets at both cutoffs. The
remaining miss is the fixture's intentional semantic-outside-shortlist case.
Fixture fingerprint:
`01ae5789f03e21bc2134098927f9ac325550cccc3d22e086231596e23178a272`.

The frozen mocked rerank benchmark scored 100/100 across ranking, abstention,
safe fallback, cache behavior, and request bounds. Fixture fingerprint:
`871bc9b829da4b7a261059fc31955e1d53895f8200c8e7a42c63ca99081bc32f`.
This measures deterministic reducer behavior against fixed typed judgments; it
does not measure live Jev model quality.

## Live Jev verification

A private-mode run against the fictional vault passed the synthetic ZDR route
gate and routed exclusively to `typesafe-ai`. Three pair judgments returned
`related`, `related`, and `none`. The provider usage receipt across the canary
and three pair calls was:

| Field | Value |
| --- | ---: |
| Requests | 4 |
| Request bytes | 4,999 |
| Input tokens | 2,683 |
| Output tokens | 213 |
| Reported cost | $0 |

An unchanged replay ran without a key and returned three cache hits, zero
pending candidates, and zero provider calls.

Private-mode search reranking evaluated three fictional hits. Their top
classifications were `supports`, `related`, and `irrelevant`; support
probabilities were 0.70, 0.01, and 0.00 respectively. The result mode was `jev`
and its answer status was `supported`. Provider usage across the canary and
three note calls was 4 requests, 2,596 request bytes, 1,592 input tokens, 149
output tokens, and $0 reported cost. Its replay made zero provider calls and
returned three cache hits.

### Live alignment benchmark

The six-case primary frozen fixture
`a6f5d73dddf70bc40249cbf489d1ac3361283c0e11fd6637d8e1e872a56f8707`
remained at 5/6 exact and 5/6 acceptable after the rubric update. The disputed
related/paraphrase case received raw top choice `duplicate` at 0.55. Because
that was below the shipped 0.65 relationship threshold, the effective result
was `unsure`; the system abstained instead of turning a weak duplicate judgment
into a link.

The independent 12-case holdout
`87a22df434ffc3902e23b4a0256b4692e4f7d0cee53f5b38a6376d45ba7313b5`
improved from 10/12 to 12/12 exact and acceptable after the rubric made revision
direction and authority/chronology rules explicit. Abstention recall improved
from 1/2 to 2/2.

| Live fixture | Requests | Request bytes | Input tokens | Output tokens | Reported cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary, 6 cases | 6 | 12,865 | 4,302 | 389 | $0 |
| Holdout, 12 cases | 12 | 25,732 | 8,673 | 775 | $0 |

These fixtures are tiny, public, and synthetic. Jev is a live provider model,
so later runs can vary. The results are bounded run receipts rather than a
general quality claim or a promise of free inference. Full methodology and
commands are in [`benchmarks/LIVE.md`](../benchmarks/LIVE.md).

See [the live canary receipt](LIVE-CANARY.md) for scope, commands, and limits.

## Stale-index safety

Provider-backed `suggest --evaluate` and `search --rerank` compare selected
source files on disk with their indexed content hashes before evaluation. A
changed, missing, escaping, or newly symlinked source fails closed with an
instruction to run `index` and retry. Regression tests verify that a hash
mismatch makes zero provider calls. Local-only search and candidate preview
remain available without a key.

## Remaining evidence gates

- Add macOS and Windows CI before claiming cross-platform verification.
- Run a separately scoped, opt-in private pilot only after its data handling
  and review plan are approved.
- Tag and publish the exact tested commit before claiming a registry release.
