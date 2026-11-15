# Verbatim excerpt from app/quality.py of AgentSuite.
# Quality metric definitions. verifiability() computes verbatim_rate as 1 - fabricated/n, a mechanical substring result; quality_for_cell() aggregates a cell over its SUCCESSFUL records.
#
# This is a READING COPY, not a runnable module. Line numbers refer to
# the original file so each excerpt can be checked against the source.

# ---- app/quality.py:73-115 ----
def verifiability(result: dict) -> dict:
    """What fraction of the run's output survives a mechanical check.

    Ground truth, not opinion: a quotation is either in the document or it is
    not. This is the metric to lead with, because a reviewer cannot argue
    with it.
    """
    claims = result.get("claims") or []
    fabricated = result.get("fabricated_quotes") or []
    notes = result.get("notes") or []

    n = len(claims)
    # Read from the structured field. It used to be recovered by regex from a
    # note, which worked until the wording changed — a quality metric parsed
    # out of prose is a quality metric waiting to silently return zero.
    bad_refs = int(result.get("malformed_references") or 0)
    if not bad_refs:
        for note in notes:
            message = note.get("message", "") if isinstance(note, dict) else ""
            m = re.match(r"(\d+) extracted reference", message)
            if m:
                bad_refs = int(m.group(1))
                break

    checks = result.get("reference_checks") or []
    resolved = sum(1 for c in checks if c.get("exists") == "confirmed")
    unresolved = sum(1 for c in checks if c.get("exists") == "not_found")

    return {
        "claims": n,
        "fabricated_quotes": len(fabricated),
        # the headline: of what it extracted, how much was real
        "verbatim_rate": (round(1 - len(fabricated) / n, 3)
                          if n else None),
        "malformed_reference_rate": (round(bad_refs / (n + bad_refs), 3)
                                     if (n + bad_refs) else None),
        "references_checked": len(checks),
        "references_resolved": resolved,
        "resolution_rate": (round(resolved / len(checks), 3)
                            if checks else None),
        "references_not_found": unresolved,
        "basis": "mechanical — substring check and index lookup",
    }

# ---- app/quality.py:261-294 ----
def quality_for_cell(records: list, pool: set, pool_counts: dict) -> dict:
    """The quality column for one experimental condition."""
    done = [r for r in records if r.get("state") == "done"]
    if not done:
        return {"runs": 0}

    def mean_of(key):
        values = [r["outcome"].get(key) for r in done
                  if r.get("outcome", {}).get(key) is not None]
        return round(statistics.mean(values), 3) if values else None

    recalls = [pooled_recall(r, pool) for r in done]
    recalls = [x for x in recalls if x is not None]
    precisions = [pooled_precision_proxy(r, pool_counts) for r in done]
    precisions = [x for x in precisions if x is not None]

    return {
        "runs": len(done),
        # mechanical, trust first
        "verbatim_rate": mean_of("verbatim_rate"),
        "malformed_reference_rate": mean_of("malformed_reference_rate"),
        "resolution_rate": mean_of("resolution_rate"),
        # human gold, where present
        "mae_vs_human": mean_of("mae_vs_human"),
        "qwk_vs_human": mean_of("qwk_vs_human"),
        "within_10_of_human": mean_of("within_10_of_human"),
        # pooled proxies
        "pooled_recall": (round(statistics.mean(recalls), 3)
                          if recalls else None),
        "corroborated_rate": (round(statistics.mean(precisions), 3)
                              if precisions else None),
        # precondition
        "stability": stability(done),
    }

# ---- app/quality.py:238-255 ----
def stability(records: list) -> Optional[float]:
    """Mean pairwise Jaccard between repeats of the same condition.

    Not quality. A precondition for it: a condition whose repeats disagree is
    not producing a stable answer, and averaging its quality scores summarises
    noise.
    """
    sets = [set(r.get("outcome", {}).get("claim_keys") or []) for r in records]
    sets = [s for s in sets if s]
    if len(sets) < 2:
        return None
    scores = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            score = jaccard(sets[i], sets[j])
            if score is not None:
                scores.append(score)
    return round(statistics.mean(scores), 3) if scores else None

# ---- app/quality.py:210-214 ----
def pooled_recall(record: dict, pool: set) -> Optional[float]:
    if not pool:
        return None
    found = set(record.get("outcome", {}).get("claim_keys") or [])
    return round(len(found & pool) / len(pool), 3)

# ---- app/quality.py:217-232 ----
def pooled_precision_proxy(record: dict, pool_counts: dict,
                           min_agreement: int = 2) -> Optional[float]:
    """What fraction of a run's claims were also found by other runs.

    A claim only one run in the whole grid ever found is more likely to be an
    extraction artefact than a claim several independent runs agree on. This
    is a proxy for precision and nothing more — a genuinely subtle claim that
    only the best condition finds is penalised by it, which is the honest
    weakness of the measure.
    """
    found = set(record.get("outcome", {}).get("claim_keys") or [])
    if not found:
        return None
    corroborated = sum(1 for k in found
                       if pool_counts.get(k, 0) >= min_agreement)
    return round(corroborated / len(found), 3)

