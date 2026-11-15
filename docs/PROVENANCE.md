# Provenance: what each claim rests on

Written for the case where the author cannot re-run anything and cannot
verify details from memory. Every row below names the artefact a claim comes
from, so a reader can check it without trusting recollection.

`analysis/check_paper_consistency.py` enforces most of this automatically.

---

## 1. Where each number in the paper comes from

| Paper element | Recomputed from | Check |
|---|---|---|
| Table I (inventory) | `data/raw/*.json` → `cells[].runs`, `.failures` | automatic |
| Table I "Calls" column | `data/events/calls.csv`, `kind=llm_call` | automatic |
| Provenance §IV-B (89.0% / 11.0% / 96 / 90) | `calls.csv` provider field | automatic |
| Fallback range 5.9–18.5% | `calls.csv`, per window/worker **cell** | automatic |
| Table II (E_v operating points) | `partitioning_v20…json`, successful runs | automatic |
| Table III (models) | `role_sizing_v1…`, `role_sizing_v11…` | automatic |
| Table IV (fan-out) | `fan_out_v1…`, `fan_out_v2…`, successes only | automatic |
| Protocol figures §V-D | `protocol_v10…json` → `quality` | manual |
| 6/3/2 windows | 34,651 chars ÷ window size | manual |
| min(2, c) extraction cap | `src/app__agents__litreview_agent.py` | manual |
| 40 claims / 40 references | run event log, fan-out A | manual |
| NeMoGuard failure mode | run event log, `structured_output` events | manual |

Items marked *manual* are stated in the paper and traceable to a named
artefact, but are not asserted by the checker.

## 2. A granularity trap worth knowing about

The paper quotes fallback as **5.9–18.5%**. Pooling the same calls by window
size instead of by window/worker cell gives **6.6–16.0%**. Both are correct;
they count different units. `verify_paper_claims.py` deliberately reports per
cell, matching the paper, and says so in its output. If you ever see 6.6–16.0
quoted against the paper, it is this, not a discrepancy.

## 3. The efficiency ranking does not replicate

The quality ordering (6k = quantity, 14k = fidelity, 28k = collapse)
replicates in both partitioning campaigns. The efficiency ranking reverses:

| Cell | Campaign A (0 failures) | Campaign B (20/45 failed) |
|---|---|---|
| 6k, 1 worker | 26.33 s | **19.90 s** ← B's best |
| 6k, 4 workers | 33.55 s | 22.21 s |
| 14k, 1 worker | **21.76 s** ← A's best | 29.75 s (n=1) |
| 14k, 2 workers | 31.55 s | 25.33 s |
| 14k, 4 workers | 25.71 s | 37.04 s (n=1) |

The cause is survivorship. Campaign B lost 20 of 45 attempts unevenly: both
14k single- and four-worker cells retain exactly one successful run each, at
743.3 s and 629.6 s against 469.8 s and 577.3 s for the same cells in
campaign A. Where most attempts in a cell fail, the completions are not a
random sample of that cell.

The paper therefore reports E_v from campaign A only, and §V-A states the
non-replication explicitly. The abstract and conclusion are scoped to "the
failure-free campaign". **Do not generalise the E_v ranking across campaigns.**

## 4. What was deliberately left out, and why

**The application database.** `suite.db` holds 4,411 rows across tables for
students (170), submissions (1,922), marking records (1,962), legal matters,
findings and settings. None of it is needed for any claim in the paper.
`analysis/export_events.py` extracts only `llm_call` and `provider_fallback`
events for the 136 experiment job ids, copying an explicit allow-list of
fields — so a new field appearing upstream cannot silently start leaking.
Re-run it against a live database with:

```bash
python3 analysis/export_events.py --db /path/to/suite.db \
    --outputs data/raw --out data/events/calls.csv
```

**The runnable harness.** `app/experiment.py` imports `app/db.py` and
`app/worker.py`, which import the finance, KTP, supervision and
publication-record modules. The closure is 54 of 93 files and includes
personal data handling. Stripping those imports would produce code that did
not run these experiments. `src/` contains verbatim excerpts instead, each
tagged with its source file and line range.

## 5. Unresolved

**Campaign B's 20 failures have no recorded cause in this package.** The
failure classification exists in the full event log (`llm_error`,
`validation_failed`, `window_unparseable` events) but was not exported here,
and the paper does not name a cause. If the original database is still
available, that is the one gap worth closing: §IV-A would be stronger for
naming what went wrong, and campaign B's survivorship effect currently rests
on an unexplained failure rate.
