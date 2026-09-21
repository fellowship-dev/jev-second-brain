# Candidate recall benchmark

This frozen synthetic corpus measures whether local candidate generation puts a
known related note inside a bounded shortlist. It makes no provider calls.

Run from the repository root:

```bash
python3 benchmark/run.py --k 3
```

The JSON result reports recall separately by relationship type and includes the
ordered shortlist, reasons, score, and rank for each expected target. A
deliberately undiscoverable relationship keeps the baseline below perfection;
it represents semantic recall that lexical and exact-link retrieval cannot yet
provide.

`truth.json` is the hand-authored oracle. Change it or the corpus only as a
versioned benchmark revision, never to fit an implementation result.
