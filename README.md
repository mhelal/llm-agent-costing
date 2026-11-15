# Resource–Quality Frontiers for Portable LLM-Agent Extraction

Data and analysis for the ICCTA 2026 paper *Beyond Bigger Models and Longer
Contexts: Resource–Quality Frontiers for Portable LLM-Agent Extraction*.

Everything in the paper's tables and figures is recomputed here from stored
measurements. Two commands reproduce the numbers:

```bash
pip install -r requirements.txt
python3 analysis/verify_paper_claims.py          # recompute every figure
python3 analysis/check_paper_consistency.py      # assert the paper matches
```

The second command exits non-zero if any number in `paper/` disagrees with
`data/`. It currently reports **55 passed, 0 failed**.

---

## What this repository is, and is not

**It is an analysis reproduction package.** The campaigns ran in August 2026
against a hosted OpenAI-compatible endpoint and a local runtime. Those
measurements are stored here in full, and every claim in the paper can be
recomputed from them offline, with no API key, no GPU and no network.

**It is not a re-execution package.** You cannot re-run the campaigns from
this repository, for two reasons, both stated plainly rather than worked
around:

1. *The models are gone.* Several endpoints used in the earlier campaigns
   have since been withdrawn from the provider's catalogue. A rerun would
   measure different models, not reproduce these.
2. *The harness cannot be separated cleanly.* The experiment ran inside a
   larger personal application. Its import graph reaches modules holding
   student records, assessment data and other personal material, so the
   runnable harness cannot be published. Publishing a *modified* harness
   with those imports removed would mean shipping code that is not the code
   that produced these results, which would be worse than shipping none.

What is published instead is `src/`: verbatim excerpts of the functions the
paper's methodological claims rest on, each labelled with its original file
and line range so it can be checked against the full application. They are
reading copies, not an importable package.

---

## Layout

```
data/raw/            the seven campaign result files, unmodified
data/events/         call-level event export (see Provenance below)
data/config/         model/role bindings and machine profile at run time
analysis/            recompute, consistency-check, export
src/                 verbatim code excerpts with line provenance
paper/               camera-ready LaTeX source and bibliography
docs/PROVENANCE.md   what each number rests on, and what it does not
```

## The campaigns

| Campaign | Factor varied | Conditions | Attempts | Failures | Calls |
|---|---|---|---|---|---|
| Partitioning A | window × workers | 9 | 27 | 0 | 462 |
| Partitioning B | window × workers | 9 | 45 | 20 | 276 |
| Role sizing A | mid-role model | 2 | 10 | 0 | 301 |
| Role sizing B | mid-role model | 3 | 9 | 3 | 138 |
| Fan-out A | workers (hosted) | 3 | 15 | 1 | 197 |
| Fan-out B | workers (local) | 3 | 15 | 1 | 90 |
| Protocol | critic rounds | 3 | 15 | 0 | 225 |
| **Total** | | **32** | **136** | **25** | **1689** |

Six campaigns run a citation-extraction agent over a 34,651-character
document. The protocol campaign runs a rubric-based assessment agent over a
different document, and is reported separately because its metrics are not
comparable with the others.

## Three results that need the event log, not just the result files

- **Realised provider is not configured provider.** 1,503 of 1,689 calls
  (89.0%) were served by the hosted endpoint and 186 (11.0%) locally. Of the
  local calls, 96 were mid-run fallbacks after a hosted failure and 90 were
  fan-out B, which was configured local end-to-end. The configured model was
  identical across the nine partitioning cells; only the event log shows what
  actually served them.
- **The 28k collapse is not a fallback artefact.** Fallback occurred in
  5.9–18.5% of calls in the 6k and 14k cells and in exactly zero calls in
  every 28k cell of both partitioning campaigns.
- **Failed runs must be excluded from timing means.** A run that aborts early
  is short, so including it pulls a cell's mean latency down. The stored cell
  aggregate for `seconds` averages all attempts; `verify_paper_claims.py`
  recomputes over successful runs only and reports both.

## Known limits of this data

Stated here so they are not discovered later:

- Repetition counts are modest and unequal. Four cells in partitioning B rest
  on one or two successful runs; their standard deviations are zero by
  construction, not by precision.
- The efficiency ranking does **not** replicate across the two partitioning
  campaigns; the quality ordering does. The cause is a 65-minute endpoint
  outage that truncated campaign B, not a property of context size. See
  `docs/PROVENANCE.md`.
- 19 of the 25 unsuccessful runs never made a model call: they were refused
  at preflight while the configured deep endpoint returned 404.
  `data/events/run_outcomes.csv` classifies all 136 runs, none unclassified.
- Verbatim fidelity is a deterministic substring criterion. It is not a
  semantic-correctness judgement, and no human-annotated subset exists.
- No TTFT/ITL telemetry was available, so the prefill/decode coefficients in
  the paper's Eq. 3 are a proposed cost model, not a fitted decomposition.

## Licensing

Three kinds of material, three different terms:

| Path | Licence | Why |
|---|---|---|
| `analysis/`, `src/` | MIT (`LICENSE`) | short, permissive, no obligations that would stop a practitioner reusing the scripts |
| `data/` | CC BY 4.0 (`LICENSE-DATA`) | software licences fit code, not measurements; CC BY is the norm for research data and is what artefact tracks expect |
| `paper/` | neither — see below | copyright transfers to IEEE on publication |

`paper/` holds the accepted manuscript. On publication, copyright in it
transfers to IEEE under the copyright form signed at camera-ready, so it is
**not** covered by the two licences above and must not be relicensed. IEEE
policy permits authors to post their own accepted version with the required
notice; add that notice to `paper/` once the proceedings notice text is issued.

Two things worth checking before pushing publicly:

- **Employment IP.** Work produced in the course of employment often vests in
  the employer rather than the author. If University of Hertfordshire policy
  applies to this code, the copyright line may need to name the university, or
  the release may need its approval. MIT is easy to grant and effectively
  impossible to revoke once published.
- **Patent grant.** If a patent grant matters to you or your institution,
  Apache-2.0 is the better choice for `analysis/` and `src/` — it is MIT plus
  an explicit patent licence and a NOTICE mechanism. MIT is chosen here
  because it is shorter, more widely understood, and nothing in this
  repository is patentable subject matter.

## Citation

```bibtex
@inproceedings{helal2026frontiers,
  author    = {Manal Helal},
  title     = {Beyond Bigger Models and Longer Contexts: Resource--Quality
               Frontiers for Portable {LLM}-Agent Extraction},
  booktitle = {International Conference on Computer Theory and Applications
               (ICCTA)},
  year      = {2026}
}
```
