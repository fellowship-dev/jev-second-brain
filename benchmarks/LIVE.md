# Live synthetic alignment benchmark

This benchmark sends six frozen, public, synthetic note pairs to Jev through
Vercel AI Gateway. It measures live classification separately from the mocked
reducer and local candidate-recall benchmarks.

```sh
AI_GATEWAY_API_KEY=... python3 benchmarks/live_alignment.py \
  --public --max-requests 6 --max-cost-usd 0.10 \
  --output /tmp/jev-live-alignment.json
```

`--public` is mandatory. The harness uses public mode, disables retries, and
refuses a request budget smaller than the frozen case count so a run cannot
silently produce partial accuracy. The report contains labels, confidence,
fixture fingerprint, confusion matrix, abstention statistics, and the complete
provider budget meter. It excludes source text, target text, raw responses,
generation identifiers, routing metadata, and credentials.

The cases cover duplicate, related paraphrase, directed revision, contradiction,
shared-word unrelated notes, and insufficient evidence. `acceptable_accuracy`
allows a conservative `related` answer for the explicit revision case while
`exact_accuracy` still measures the stricter expected label.

The report preserves Jev's raw `model_choice` and confidence for diagnosis,
then applies the same minimum probability used by the shipped alignment
pipeline. A raw top choice below that threshold has effective `predicted` label
`unsure`; accuracy, confusion, and abstention use this effective label.

Use the separate 12-case public synthetic holdout when evaluating a rubric
change out of sample:

```sh
AI_GATEWAY_API_KEY=... python3 benchmarks/live_alignment.py \
  --public --fixture benchmarks/fixtures/alignment_holdout_cases.json \
  --max-requests 12 --max-cost-usd 0.20 \
  --output /tmp/jev-live-alignment-holdout.json
```

Keep the primary fixture and expected labels unchanged when running the
holdout. Its hard cases emphasize duplicate-versus-related boundaries across
incident response, cooking, finance, and horticulture, plus revision direction,
contradictions, shared words without a relationship, and ambiguous evidence.

## Recorded results

These are receipts from live Jev runs, not fixed expectations for future model
behavior. Both fixtures are small, public, and synthetic. Provider behavior can
vary even when the fixture and rubric hashes do not.

### Primary fixture

- Fingerprint:
  `a6f5d73dddf70bc40249cbf489d1ac3361283c0e11fd6637d8e1e872a56f8707`
- Before and after the rubric clarification: 5/6 exact, 5/6 acceptable.
- Disputed related/paraphrase pair: raw top choice `duplicate` at 0.55;
  effective prediction `unsure` after the shipped 0.65 threshold.

The miss is conservative: a weak duplicate classification does not become a
relationship proposal. This fixture therefore checks both classification and
the deterministic abstention boundary.

| Usage | Value |
| --- | ---: |
| Requests | 6 |
| Request bytes | 12,865 |
| Input tokens | 4,302 |
| Output tokens | 389 |
| Reported cost | $0 |

### Independent holdout

- Fingerprint:
  `87a22df434ffc3902e23b4a0256b4692e4f7d0cee53f5b38a6376d45ba7313b5`
- Before rubric clarification: 10/12 exact, 10/12 acceptable.
- Final run: 12/12 exact, 12/12 acceptable.
- Abstention recall: 1/2 before, 2/2 final.

The final rubric states revision direction and authority/chronology rules
explicitly. The holdout improved without editing its cases or expected labels.

| Usage | Value |
| --- | ---: |
| Requests | 12 |
| Request bytes | 25,732 |
| Input tokens | 8,673 |
| Output tokens | 775 |
| Reported cost | $0 |

The provider reported zero cost for these two runs. That observation does not
promise zero cost, quota, or identical classifications on a later run.
