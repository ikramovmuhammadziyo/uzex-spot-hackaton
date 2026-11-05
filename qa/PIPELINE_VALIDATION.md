# Pipeline validation — 2026-11-05

Implemented plan: [plan/10_eval_failure_remediation.md](../plan/10_eval_failure_remediation.md).

## Deterministic checks

- `.venv/bin/python -m pytest -q`: **101 passed**.
- `.venv/bin/python qa/qa_recompute.py`: **151/151 original CSV anchors reproduced**.
  This checks consistency of the historical key, not dimensional validity of every
  old metric. Version 2 no longer requires the mixed-unit physical grand total.
- `.venv/bin/python -m qa.recompute_variants`: independent all/noncancelled/completed
  references. Largest remaining mass at one partial-delivery deal is **2,980 tonnes**,
  rather than the largest raw kilogram/lot count. CSV and DuckDB checks agree.
- `git diff --check`: clean.

Tests cover Decimal rounding, signs, small numbers, exact identifiers, date displays,
prose/JSON separation, source-cell/entity/scope checks, truncated/budget-bound synthesis,
partial refusal verification, cache invalidation and eviction, volatile SQL bypass,
registry/region audit calculations, and commodity normalization against CSV data.

## Live evaluation

The last full run was
[`20261105T052535826953Z`](runs/20261105T052535826953Z/eval_results.json):
**99/117** numeric checks matched. Its only failed question was case 03, where list
cleanup incorrectly stripped the year before a closing parenthesis. That parser
regression was fixed and locked down with a test.

A fresh case-03 run then passed **18/18**:
[`20261105T053037052639Z`](runs/20261105T053037052639Z/eval_results.json).
The global-versus-annual broker metadata was clarified and a fresh case-06 run passed
**13/13**:
[`20261105T054052171594Z`](runs/20261105T054052171594Z/eval_results.json).

Latest explicit attempts by case (not best-of scoring):

| Case | Required numeric checks | Source |
|---|---:|---|
| 01 Export | 8/8 | Last full run |
| 02 Auctions | 19/19 | Last full run |
| 03 States/deposits | 18/18 | Fresh case-03 rerun |
| 04 Remaining delivery | 6/6 | Last full run, corrected mass rubric |
| 05 Physical ranking | 3/3 | Last full run |
| 06 Brokers | 13/13 | Fresh case-06 scope check |
| 07 Integrity | 20/20 | Last full run |
| 08 Discipline | 11/11 | Last full run |
| 09 Regions | 7/7 | Last full run |
| 10 YTD | 12/12 | Last full run |
| **Total** | **117/117** | Full run plus targeted reruns |

The captured full run also passes **117/117** when replayed through the corrected
verifier:
[`verifier_replay.json`](runs/20261105T052535826953Z/verifier_replay.json).
That is a deterministic replay of archived evidence and bindings, **not** a new
full generation run or proof of model stability.

The two original questions were also run without benchmark metric/entity hints:
[`20261105T042721621811Z`](runs/20261105T042721621811Z/eval_results.json).
Case 05 returned the correct noncancelled-basis leaders (2,187,806 t wheat,
1,277,077 t cement, 1,267,043.77 t cotton) and explained incompatible dimensions.
Case 08 returned supported payment/delivery figures instead of a blanket refusal;
it unnecessarily marked the category conclusion provisional despite earlier evidence.
Repair instructions now explicitly preserve earlier successful current-turn evidence.
Original-mode cases require declared-basis/semantic review; their zero bound-metric
score is not an answer-accuracy score.

## Interpretation and limits

Canonical runs specify state basis and metric/entity labels for structured binding;
they provide no expected numeric values. Original-mode runs test unhinted discovery.
Numeric matching is separate from prose semantics, ranking completeness, coverage,
and refusal correctness. Those fields remain `needs_review` in raw artifacts rather
than being automatically declared correct. The generated text was inspected for
major domain traps, but this is not a claim of universal semantic correctness.

Earlier development runs exposed and reproduced additional issues: gross/net basis
mismatch, loss of metric metadata during repair, regional key-join versus label
agreement confusion, scaled SQL aliases, internal JSON leakage, and long-answer
truncation. Read-only audit and mass-ranking primitives reduce query exploration;
values are computed from the connected snapshot, not stored answers.

Live generation still varies in latency, phrasing, and number of repair calls.
No statistical reliability claim is made from these few runs. Cache correctness is
covered by deterministic tests; no end-to-end latency improvement percentage is
claimed. Final-answer caching, semantic caching and provider-specific prompt caching
remain deferred.

All new live artifacts are ignored under `qa/runs/` and the runner never writes the
historical `qa/eval_results.json`. A separate manual update to that baseline's case 05
appeared during this task and was preserved; it is not part of this implementation.
