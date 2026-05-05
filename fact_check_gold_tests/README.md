# Fact-check gold corpus tests

Add these two files near your existing `test_fact_check_skill.py`:

```text
tests/gold_fact_check_cases.py
tests/test_fact_check_gold_corpus.py
```

The corpus contains 72 deterministic claims. Each case includes:

- `claim`
- `expected_verdict`: `SUPPORTED`, `REFUTED`, or `INSUFFICIENT`
- `expected_score`: `1.0`, `0.0`, or `0.5`
- `source_types`
- `edge_cases`
- `source_specs`: fixture connector results used by the test

The tests intentionally use fixture evidence rather than live web results so that future connector and policy changes are measured against the same cases.

Run with:

```bash
pytest tests/test_fact_check_gold_corpus.py
```
