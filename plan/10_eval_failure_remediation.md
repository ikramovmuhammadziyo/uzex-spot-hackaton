# Evaluation failure remediation plan

## Scope and evidence

Reviewed `qa/eval_results.json` (2026-11-05, ten cases, 58/124 anchors matched),
`QA_10_HARD_TESTS.md`, the evaluator, prompts, agent loop, and guardrails.
This plan is implemented in the working tree. This work does not overwrite the original evaluation artifacts;
new live runs are stored separately. Execution details and validation are recorded below.
The stored score measures the current text matcher, not reliable answer correctness.
The QA document also contains retry observations; those are separate from this JSON run.

Two guardrail defects were reproduced locally through the actual verifier:

- Evidence `7704993702929.156` does not support its correctly rounded display
  `7 704 993 702 929,16`.
- An unsupported `999999999 сум` passes verification when the answer also contains
  the standard no-answer phrase.

Both checks failed under `.venv/bin/python` using `EvidenceIndex` and `verify_answer`.
Case 05's budget-exhaustion explanation is supported by the existing QA retrospective
and the loop's missing finalization path; the JSON itself contains only the empty-answer
exception, not a complete round-by-round trace. Reproduce with a scripted LLM before fixing.

## Case-by-case triage

| Case | Stored anchors | Finding | Required action |
|---|---:|---|---|
| 01 Export FX | 4/8 | Correct on disclosed noncancelled basis; key includes cancelled. Correct rounding causes regeneration. | Basis-aware scoring; decimal display verification. Preserve per-deal FX. |
| 02 Auctions | 5/19 | Different state basis; exact-start definition differs; net percentage of turnover omitted. Negative values are not scored reliably. | Explicit equality/tolerance rule, signed scoring, coverage checklist, consistent denominator. |
| 03 States | 16/18 | Useful full distribution; unsigned deals described as definitively not materialized; all-deal deposit metric omitted. | Distinguish pending from cancelled and contractual exposure from actual deposit receipts. Test requested deposit coverage. |
| 04 Partial delivery | 7/7 | Matcher passes an unusable sum of heterogeneous units. Largest physical backlog is not defensible across dimensions. Lot-based fill ratio needs a limited interpretation. | Split physical backlog by unit; rank within dimensions; label lot ratio as such, prefer value-weighted ratio for an overall economic measure. Fix rubric too. |
| 05 Volume | 0/5 | Empty-answer exception in this run, rather than a substantive answer. A generic refusal is also wrong for this question. | Guaranteed finalization, TN VED grouping, tonne normalization, answer supported subparts. |
| 06 Brokers | 5/13 | State-basis difference; broker-side wording calls brokers sellers. | Basis-aware metrics; distinguish representing sellers from being sellers; preserve separate annual/global activity windows. |
| 07 Integrity | 18/22 | Broadly useful audit; zero counts expressed in words evade matcher. Some anchors exceed the actual question, e.g. weekend count. | Evaluate explicit facts, allow supported verbal zero, mark optional probes separately. |
| 08 Discipline | 0/11 | Queries ran; verifier rejected rounded/derived numbers and substituted a false data-absence claim. | Numeric verification and separate verification failure from absent data; compute all reported metrics in SQL. |
| 09 Regions | 2/8 | Correct disclosed basis; schema incorrectly calls deal region warehouse region. Regeneration produces an unnecessary correction to an unseen draft. | Correct schema semantics, key-based join explanation, prevent internal revision text leaking. |
| 10 YTD | 1/13 | Completed-only differs from key; top-ten concentration omitted; mixed refusals mark entire response no-answer and bypass checking. | Stable status policy, full metric coverage, partial-answer classification, verify supported sections. |

Do not interpret the five basis differences as fabricated numbers. Equally, do not
declare all answers correct merely because their numeric values can be reproduced:
scope, coverage, field meaning, and dimensional validity also matter.

## Intended structure

Keep the existing database, tools, and orchestration. Add small boundaries as needed:

```text
question + history
  -> analysis specification (period, basis, dimensions, requested outputs)
  -> bounded SQL execution (typed result evidence)
  -> supported claims + unavailable subparts
  -> verification (metric, entity, unit, basis, precision)
  -> answer rendering + explicit outcome
```

The specification should carry requested/effective dates, snapshot date, state policy,
commodity key, measure (contracted versus delivered), and a list of requested outputs.
Use an internal dataclass first; avoid another autonomous agent or mandatory extra
model call. Simple questions should retain a short execution path.

Use `tnved_code` as the commodity key for this QA pack, with a returned display label.
Check unit compatibility within each code. A TN VED code is the declared aggregation
grain, not proof that every possible product variant is interchangeable.

Keep SQL responsible for arithmetic. Typed evidence should retain query ID, column,
row/entity keys, raw decimal value, unit, basis, and display precision. Start by keeping
column and row metadata already returned by `run_sql`, then add claim references where
needed. A renderer can format a validated value without asking the model to repeat it.

Outcome categories: `answered`, `partial`, `no_data`, `unsupported_request`,
`verification_failed`, `execution_failed`. A failed query or rejected draft must not
be presented as evidence that the registry lacks the answer.

## Implementation sequence

### 1. P0 — Freeze baseline and repair evaluation contracts

Files: `qa/run_eval.py`, `qa/anchors_data.py`, `qa/qa_recompute.py`,
`QA_10_HARD_TESTS.md`; new versioned case specifications under `qa/cases/`.

- Preserve original JSON and report as immutable baseline artifacts. New runs get IDs
  and separate files; selected-case runs must not overwrite the full baseline.
- Each metric needs ID, entity, period, state basis, unit, expected value, explicit
  tolerance, required/optional flag, and source computation.
- For canonical benchmark runs, make the question explicitly request the key's basis.
  For original ambiguous questions, score declared supported bases against independently
  recomputed variants. Never select whichever basis happens to give the best score.
- Keep noncancelled as the default turnover basis; explicit user instructions override
  it. Completed-only must be requested or clearly justified. Plain registry counts use
  all rows. State distributions necessarily include all requested states.
- Replace “number appears anywhere” matching. Case 01 currently credits 1,367 even
  though it appears as the all-export count, not the headline noncancelled metric.
- Preserve signs, associate units and entities, and use declared tolerances without
  silently expanding them to 0.5%. Score semantic checks separately from numeric ones.
- Require mixed-unit caveats and useful supported results; do not require invalid totals
  just because they appear in the original answer key.

Acceptance: wrong entity, wrong sign, wrong unit, and wrong basis fixtures fail;
correct disclosed-basis fixtures pass; an unrelated number cannot satisfy an anchor.

### 2. P0 — Repair verifier and refusal classification

Files: `services/guardrails.py`, `services/agent.py`, `tests/test_guardrails.py`.

- Recognize whole-response refusals only as whole-response refusals. Empty text is an
  execution failure. Mixed responses still undergo numeric/name verification.
- Replace permissive digit-string variants with Decimal parsing and unambiguous locale
  rules. Preserve signs. Accept rounding at the displayed precision with a defined
  rounding mode; do not add a general percentage tolerance.
- Attach scaling to explicit units (billion/trillion); keep dates, IDs, INNs, and broker
  codes exact. Validate small counts and percentages too: the current significance
  shortcut ignores many one/two-digit claims.
- Preserve evidence for requested period boundaries separately from observed min/max
  dates. A SQL upper bound is not automatically an observed transaction date.
- Keep rejected draft diagnostics and failure status. Never set a fallback refusal to
  `guardrail_ok=True` as though the substantive answer passed.
- Where mapping is available, require the value to belong to the claimed metric/entity;
  matching an unrelated value somewhere in the result set is insufficient.

Acceptance: both local reproductions become green; negative/sign and identifier
counterexamples stay rejected; case 10's factual sections cannot bypass verification.

### 3. P0 — Guarantee bounded finalization

Files: `services/agent.py`, `services/llm.py`, `tests/test_agent.py`.

- Separate query budget, repair budget, and a reserved final synthesis call. After the
  last allowed tool round, request synthesis with tools disabled using the client's
  supported interface (extend it explicitly if necessary).
- Pass a compact coverage/evidence summary. Return supported subanswers and explicit
  limitations rather than discarding successful queries. Verify the final response.
- If synthesis is still empty, report an execution failure. Do not invent an answer
  from unlabelled rows and do not describe the data as absent.
- Add a scripted LLM fixture that always requests tools until the budget is exhausted;
  assert final synthesis occurs and the total calls remain bounded. Cover empty replies,
  all SQL failures, and failed repair separately.

Acceptance: case-05-shaped replay produces a nonempty verified partial/full answer
when sufficient evidence exists; unavailable synthesis yields an honest service error.

### 4. P1 — Fix analytics semantics and partial answers

Files: `services/prompts.py`, optional small `services/analysis_spec.py`,
`tests/test_agent.py`, `tests/test_tools.py`, QA reference computations.

- Correct deal `region` to seller-company region; contract region is warehouse region.
  Join on identifiers, never on translated region labels. Distinguish label mismatch
  from an inability to join the records by their keys.
- For physical-volume rankings, group by TN VED, calculate `quantity * lot`, convert
  kilograms to tonnes, and rank mass-compatible commodities. Keep litres, pieces,
  lengths, areas, and cubic metres separate. No assumed densities.
- For case 05, provide the mass top three, grouping rule, date coverage, state filter,
  and explanation that no overall cross-unit physical total exists.
- Replace global no-answer instructions for missing density/profit/VAT/forecast with
  subquestion-level limitations. Supported parts must still be answered.
- For case 04, compute remaining physical quantities per unit and value in UZS;
  show largest backlog within a declared comparable unit or rank by UZS value.
- Clarify that partial execution is not full delivery; current statuses are a
  30.10.2026 snapshot, not reconstructed historical year-end statuses.
- Same-window YTD comparisons must use the same state filter and explain snapshot
  maturity bias. Completed-only comparison does not eliminate that bias.

Acceptance: independent CSV recomputation matches TN VED mass rankings for each
supported basis; tonnes/kg combine correctly, other dimensions never do. Validate
all requested supported subparts, rather than blanket refusal.

### 5. P1 — Coverage and answer composition

Files: `services/prompts.py`, `services/agent.py`, QA case specifications.

- Make response length proportional to question complexity; retain concise defaults
  without imposing 2–5 lines on multi-part audits.
- Track requested outputs as answered, unavailable with reason, or unresolved.
  Cases 02 and 10 must include net percentage and top-ten buyer concentration.
- Return derived percentages/deltas as SQL columns on the first aggregate query.
  Round for presentation after calculation, without repeated SQL solely to satisfy
  a text matcher.
- Prevent revision instructions from producing “correction to previous answer” when
  only an internal draft existed. Describe broker roles precisely.
- Explain definitions: exact-start equality versus stated rounding tolerance;
  theoretical deposit exposure versus recorded payments; pending versus cancelled.

Acceptance: a coverage checklist passes for all ten cases, including limitations,
without requiring optional facts absent from the user's question.

### 6. P2 — Observability and stability gates

- Record per-round tool results/errors, finish reason, budget remaining, final outcome,
  verifier failures, regeneration reason, metric coverage, token usage, and latency.
  Preserve tool evidence needed for replay; exclude credentials and secrets.
- Report numeric correctness, semantic correctness, coverage, refusal correctness,
  execution success, and cost separately. `ok=True` must not mean only “returned text”.
- Run deterministic tests first, then ten canonical cases plus original ambiguous
  variants. Repeat the live suite at least three times and report observed failures;
  do not claim a population failure rate from ten cases or isolated retries.

Release gates: deterministic regressions pass; no empty successful answers; no false
data-absence fallback for verification/budget failures; no mixed-unit totals; complete
required outputs; correct basis, signs, units, and YTD windows. Compare latency and
tokens with baseline, and investigate regressions before increasing budgets globally.

## Delivery structure

## Cache implementation and boundaries

Add a bounded, process-local LRU around successful deterministic tool calls. Key by
connected dataset generation (file identity/size/mtime at connection), tool name,
exact JSON arguments, and row limit. Keep immutable serialized payloads; mark hits
and misses outside the fact payload. Cached results enter the same current-turn
evidence path as fresh results. Clear on dataset-generation changes. Never cache
errors or model answers, and bypass volatile SQL (time/random/session functions).
Use configurable entry and byte limits; expose per-answer hit/miss counts. No TTL
is needed for immutable connected snapshots. Reconnect when replacing the database;
do not silently mix a new disk file with an existing DuckDB connection.

Final-answer/semantic caches and provider-specific prompt caching are deliberately
deferred until correctness is established. They need conversation-aware keys and
provider-specific validation. Stable prompt blocks remain before user history.

Cache acceptance: repeated exact calls avoid DB execution; failures are retried;
different literal arguments/row limits/generations never share entries; size and LRU
eviction are bounded; cached evidence verifies identically in a later turn.

## Execution checklist

1. Freeze existing evaluation artifacts; add explicit versioned benchmark contracts
   and structured metric scoring, with unbound prose marked for review.
2. Reproduce numeric and mixed-refusal failures, then repair Decimal verification.
3. Add explicit outcomes, reserved synthesis, structured coverage, and tool traces.
4. Update dimensional, commodity, region, state, and multi-part answer instructions.
5. Add bounded tool caching and dataset-generation invalidation.
6. Run offline regressions and independent data recomputation; run versioned live
   evaluations when the configured endpoint is available. Record actual results and
   limitations below; never replace the original baseline.

## Delivery structure (review units)

Implement in reviewable changes: (1) versioned evaluation contracts and scorer tests,
(2) verifier/outcome fixes, (3) bounded finalization, (4) commodity/region/state semantics,
(5) coverage and run reporting. Steps 2 and 3 can be independently reviewed after the
baseline is frozen; full re-evaluation follows all steps. Avoid a model migration or
large orchestrator rewrite until these deterministic defects have been addressed.

## Implemented structure and findings from validation

- `services/analysis_spec.py`: declared requested/effective scope, state basis,
  grouping, measure, requested outputs, and application-owned snapshot date.
- `services/answer_contract.py`: internal JSON parsing, coverage tracking, outcome
  classification, source-cell binding and deterministic monetary display scaling.
  Missing declared outputs become unresolved; scope is not treated as data evidence.
- `services/guardrails.py` / `numeric.py`: Decimal parsing, presentation rounding,
  strict identifiers/signs, small-value checks, scoped dates, mixed-refusal verification.
- `services/agent.py`: reserved bounded synthesis (including output truncation), one
  repair that preserves the full envelope and all earlier current-turn evidence,
  explicit failures, typed result provenance, coverage, query/cache metrics and traces.
- `services/tool_cache.py`, `tools.py`, `database.py`: bounded LRU for deterministic
  successful results; snapshot generation validation, exact argument keys, volatile
  SQL bypass, and normal evidence handling on cache hits.
- Three reusable read-only tools address observed semantic/budget failures:
  `registry_audit` computes full inventory/integrity in one SQL query;
  `region_audit` distinguishes key-join coverage from label equality;
  `mass_ranking` normalizes kg/tonnes for commodities or individual deals and supports
  contracted, delivered, and remaining quantities. They contain SQL, not stored answers.
- `qa/cases`, `scoring.py`, `recompute_variants.py`, and `replay_verification.py`:
  versioned explicit contracts, metric-bound scoring, independent CSV basis variants,
  and reproducible verifier replay. Model/entity labels are supplied for canonical
  structured scoring; original questions are separately checked without those hints.

Live validation exposed additional defects now covered by regressions: Markdown
between amount/unit, inline list ordinals, citation ordinals, relative date display,
requested forecast years, prose plus internal JSON, long/truncated JSON, aliases such
as `bn_uzs_all_states`, and reuse of earlier evidence during repair. Monetary source
references handle at most one binary ULP when the model emits a JSON float; this is
serialization handling, not a general numeric accuracy tolerance.

Two old rubric assumptions were corrected instead of implementing them: mixed physical
units do not have a valid sum, and the largest raw remaining count (302,376 kg) is not
largest remaining mass. Independent CSV recomputation finds 2,980 tonnes for the latter.
The original workbook/JSON were not rewritten by this implementation. A separate
manual annotation to baseline JSON case 05 appeared during the task and was preserved.

Coverage and scope remain model declarations. Numeric verification does not prove all
prose semantics; source-cell/entity checks and manual semantic review are reported
separately. Final-answer caching, semantic caching, provider-specific prompt caching,
and a model migration remain deferred as discussed.

See `qa/PIPELINE_VALIDATION.md` for commands, recorded live results and remaining limits.
