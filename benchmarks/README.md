# Rerank benchmark

Run the frozen mocked Jev reducer benchmark directly from the repository root:

```sh
python3 benchmarks/rerank_benchmark.py
```

The command needs no API key and makes no network calls. It reports separate
scores for ranking, abstention, safe fallback, cache behavior, and request
bounds. The fixture fingerprint makes changes to the committed evaluation set
visible. This benchmark measures deterministic reducer behavior against fixed
typed judgments; it does not measure live Jev model quality.
