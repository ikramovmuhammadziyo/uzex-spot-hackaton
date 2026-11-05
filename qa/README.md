# Pipeline QA

`eval_results.json`, `eval_report.xlsx` and the retrospective in
`../QA_10_HARD_TESTS.md` are the historical baseline (the JSON may also contain separate manual annotations). The workbook's manual reviews
apply only to that baseline. Do not reuse them to judge a fresh run.

Version 2 case contracts live in `cases/`. Each metric records its entity, state
basis, period, units, tolerance, required/optional flag, and independent reference.
Invalid mixed-unit totals are not required. Canonical questions explicitly request
the gross/all-state basis used by the frozen key. Metric bindings supplied to the
model contain no expected numeric values, but do include metric/entity labels for
structured binding. Use original mode for unhinted discovery questions. Numeric grading uses source-cell references;
entity, basis, period, signs and units must agree. Prose and semantic checks remain
`needs_review` until reviewed, even when every number matches.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python qa/qa_recompute.py
.venv/bin/python -m qa.recompute_variants
.venv/bin/python qa/run_eval.py
.venv/bin/python qa/run_eval.py 5 8
.venv/bin/python qa/run_eval.py --original
.venv/bin/python -m qa.replay_verification qa/runs/RUN_ID/eval_results.json
```

Install development dependencies from `requirements-dev.txt`. The reference scripts
use CSVs independently of DuckDB. `recompute_variants` supplies explicit all,
noncancelled and completed bases for cases 01, 02, 05, 06, 09 and 10. Original ambiguous
questions require declared-basis review; the runner never picks whichever basis
scores best. Replays validate captured evidence with today's verifier; they are
not new model runs and cannot demonstrate generation stability.

Live runs archive their exact case contract and fingerprint, call the configured endpoint and write to a new, ignored
`qa/runs/<UTC timestamp>/eval_results.json` directory, including errors and partial
runs. Original baseline artifacts are never overwritten. A canonical run exits
nonzero if execution/verification fails or a required bound metric does not match.
Tool traces and typed source results allow local diagnosis. Review output text for
coverage, denominator, dimensional validity, and unsupported conclusions separately.

Caching is per `ToolRunner`, so multiple questions in a single run can reuse exact
queries against the same snapshot. Independent runs start with an empty cache.
Unit tests exercise eviction, invalidation, failure bypass, volatile SQL, and
verification of cached results on a later turn.

The version 2 backlog case also corrects a semantic error in the old rubric:
maximum raw lots/kg is not maximum mass. `Q4_max_und_lots` is optional; the
canonical mass comparison uses `Q4_max_und_mass_t`, independently recomputed from
CSV by `recompute_variants`. The frozen original answer key remains historical.
