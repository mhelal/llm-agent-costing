# Verbatim excerpt from app/agents/litreview_agent.py of AgentSuite.
# Windowed extraction and the two fan-out stages. The extraction map_reduce is capped at min(2, max_workers); the verification map_reduce uses the full worker count.
#
# This is a READING COPY, not a runnable module. Line numbers refer to
# the original file so each excerpt can be checked against the source.

# ---- app/agents/litreview_agent.py:288-307 ----
def _windows(text: str, size: int, overlap: int) -> list[str]:
    """Split into overlapping windows, preferring paragraph boundaries.

    The overlap exists so a claim spanning a boundary is not lost; the
    duplicate it produces is removed afterwards by quote text.
    """
    if len(text) <= size:
        return [text]
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind("\n\n", start + size // 2, end)
            if cut > start:
                end = cut
        out.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out

# ---- app/agents/litreview_agent.py:310-665 ----
def check_review(
    *,
    document_id: str,
    text: str,
    topic_hint: str = "",
    model: str = MID,
    progress: Progress = None,
    max_claims: int = 60,
    max_workers: int = 4,
    skip_claim_checks: bool = False,
    skip_lookups: bool = False,
    skip_synthesis: bool = False,
    extract_window: int = 14000,
    steer: str = "",
    context_block: str = "",
    thinking_budget: Optional[int] = None,
) -> LitReviewResult:
    budget = Budget(max_turns=500, max_seconds=7200, max_output_tokens=500_000)
    notes: list[AgentNote] = []

    if progress:
        progress("extracting claims")
    runlog.info(f"document is {len(text):,} characters; extracting up to "
                f"{max_claims} claims")

    # Extract in windows rather than one enormous call.
    #
    # The single-call version asked for up to 16,000 output tokens. At the
    # 20-30 tokens/second a hosted 70B actually delivers, that is eight to
    # thirteen minutes in one HTTP request — long enough that any sensible
    # timeout fires, and if it does the whole document's extraction is lost.
    # Windowed extraction makes each call short and survivable, gives
    # progress, and lets one bad window fail without taking the rest with it.
    windows = _windows(text, size=extract_window, overlap=600)
    runlog.info(f"extracting over {len(windows)} window(s) of ~{extract_window:,} chars")

    unparseable_windows: list[int] = []
    skipped_reference_windows: list[int] = []

    def extract_window_claims(pair):
        index, chunk = pair
        runlog.info(f"extractor on window {index + 1}", kind="agent_turn",
                    agent="extractor", window=index + 1)
        if is_reference_block(chunk):
            skipped_reference_windows.append(index + 1)
            runlog.info(f"window {index + 1} is a reference list — skipped "
                        "without a model call", kind="window_skipped",
                        window=index + 1)
            return []
        if progress:
            progress(f"extracting claims {index + 1}/{len(windows)}")
        try:
            result = structured(
                ExtractedClaims, model=model, system=EXTRACT_SYSTEM,
                messages=[{"role": "user", "content":
                           f"<topic_hint>{topic_hint}</topic_hint>\n"
                           f"<review_part index='{index + 1}' "
                           f"of='{len(windows)}'>{chunk}</review_part>"}],
                # Scaled to the cap rather than fixed. A flat 3000 was ample
                # at max_claims=20 and truncated constantly at 40: the
                # response was cut mid-array, the JSON never closed, and the
                # repair call truncated in the same place.
                #max_tokens=max(2000, min(12000, 90 * max_claims + 600)),
                max_tokens=max(4000, min(16000, 120 * max_claims + 800)),
                budget=budget, temperature=0.0,
                thinking_budget=thinking_budget,
            )
            return result.claims
        except Exception as exc:                            # noqa: BLE001
            # A window that will not parse is a window with no claims, not a
            # dead run. It happens reliably on the parts that are almost
            # entirely reference list: with nothing to extract, the model
            # writes a summary instead, and no amount of repair turns prose
            # into JSON. Losing that window costs the claims it did not
            # contain. Losing the run costs everything.
            unparseable_windows.append(index + 1)
            # The exception's actual message is where a 400's real reason
            # lives — a rejected schema, an unsupported parameter, a bad
            # combination of request fields. Logging only the exception's
            # TYPE name (as this used to) discards exactly the information
            # needed to tell "the model wrote prose instead of JSON" apart
            # from "the API rejected the request outright before any
            # generation happened" — two different problems that this
            # window being empty cannot distinguish on its own.
            runlog.warn(f"window {index + 1} produced no parseable output "
                        f"({type(exc).__name__}: {str(exc)[:300]}) — treated "
                        "as empty. This is usual for a part that is only "
                        "references; it is NOT usual if every window in "
                        "the job fails identically — that pattern means "
                        "the request itself is being rejected, not that "
                        "the content is unparseable.",
                        kind="window_unparseable", window=index + 1)
            try:
                # Retry with a valid max_tokens
                result = structured(
                    ExtractedClaims,
                    model=model,
                    system=EXTRACT_SYSTEM,
                    messages=[{"role": "user", "content": 
                            f"<topic_hint>{topic_hint}</topic_hint>\n"
                            f"<review_part index='{index + 1}' "
                            f"of='{len(windows)}'>{chunk}</review_part>"}],
                    max_tokens=max(4000, min(16000, 120 * max_claims + 800)),  # <-- FIXED
                    budget=budget,
                    temperature=0.0,
                    thinking_budget=thinking_budget,
                )
                return result.claims
            except Exception as retry_exc:
                runlog.warn(f"retry also failed: {type(retry_exc).__name__}: {str(retry_exc)[:200]}")
                            # DEBUG: Log what was actually returned
                import logging
                logging.info(f"Extractor raw response: {result.model_dump_json()[:500]}")
                return []




    collected: list[CitationClaim] = []
    with runlog.stage("extract claims"):
        if len(windows) == 1:
            collected = extract_window_claims((0, windows[0]))
        else:
            for group in map_reduce(list(enumerate(windows)),
                                    extract_window_claims,
                                    reducer=lambda rs: rs,
                                    max_workers=min(2, max_workers)):
                collected.extend(group)

    # A citation whose `cited_as` is simply the claim sentence is not a
    # citation. Under a provider without constrained decoding the extractor
    # does this often enough to matter, and it produced two "references" in
    # one run that were sentences from the review itself — each then dutifully
    # looked up in Crossref and reported as not found, which reads like a
    # fabricated reference and is nothing of the kind.
    rejected_refs = 0
    kept: list[CitationClaim] = []
    for claim in collected:
        ref = " ".join(claim.cited_as.lower().split())
        quote = " ".join(claim.claim_text.quote.lower().split())
        if ref and quote and (ref == quote or (len(ref) > 40 and ref in quote)):
            rejected_refs += 1
            continue
        kept.append(claim)
    if rejected_refs:
        runlog.warn(f"{rejected_refs} extracted 'reference(s)' were just the "
                    "claim sentence repeated, not a citation — dropped before "
                    "any lookup", kind="bad_extraction")
        notes.append(AgentNote(
            level="warning",
            message=(f"{rejected_refs} extracted reference(s) were the claim "
                     "text repeated rather than a citation, and were dropped. "
                     "That is an extraction failure, not a fabricated "
                     "reference by the author. It happens more on providers "
                     "without native structured output.")))
    collected = kept

    # A review full of citation markers that yields no claims has not been
    # analysed; it has been skipped. That is a failure the previous version
    # reported as a clean success — every run "done", every count zero — and
    # a silent zero is the worst possible result because it looks like data.
    if not collected:
        markers = len(_REF_MARKER.findall(text))
        if markers >= 10:
            raise RuntimeError(
                f"No claims were extracted, yet the document contains about "
                f"{markers} citation marker(s). An empty result from a text "
                "that plainly cites other work means the extractor returned "
                "empty arrays rather than doing the work — not that the "
                "review makes no claims. Treat this run as failed. It is "
                "usually a provider ignoring the schema; try one with native "
                "structured output.")
        notes.append(AgentNote(
            level="warning",
            message=("No claims were extracted. The document contains few "
                 "citation markers, so this may be correct — but check "
                     "the document converted properly before believing it.")))

    seen_quotes: set[str] = set()
    deduped: list[CitationClaim] = []
    for claim in collected:
        key = " ".join(claim.claim_text.quote.lower().split())[:160]
        if key and key not in seen_quotes:
            seen_quotes.add(key)
            deduped.append(claim)

    class _Extracted:
        claims = deduped

    extracted = _Extracted()
    if skipped_reference_windows:
        runlog.info(f"{len(skipped_reference_windows)} window(s) skipped as "
                    "reference lists, saving that many model calls")
        notes.append(AgentNote(
            level="info",
            message=(f"{len(skipped_reference_windows)} of {len(windows)} "
                     "window(s) were bibliography and were skipped without a "
                     "model call. A reference list contains the cited works, "
                     "not claims about them.")))

    attempted = len(windows) - len(skipped_reference_windows)
    if unparseable_windows:
        if attempted and len(unparseable_windows) >= attempted:
            raise RuntimeError(
                f"None of the {attempted} window(s) with prose produced "
                "parseable output. The "
                "model returned prose rather than JSON throughout, which "
                "usually means the provider is ignoring the schema "
                "instruction entirely. Try a provider with native structured "
                "output, or a different model.")
        notes.append(AgentNote(
            level="warning",
            message=(f"{len(unparseable_windows)} of {len(windows)} window(s) "
                     f"produced no parseable output (parts "
                     f"{', '.join(str(w) for w in sorted(unparseable_windows))}"
                     ") and were treated as empty. Claims in those parts are "
                     "missing from this run, so treat the counts as a lower "
                     "bound.")))

    runlog.info(f"{len(collected)} claim(s) extracted from "
                f"{len(windows) - len(unparseable_windows)}/{len(windows)} "
                f"window(s), {len(deduped)} after removing overlap duplicates")
    claims = extracted.claims[:max_claims]
    if len(extracted.claims) > max_claims:
        notes.append(AgentNote(
            level="warning",
            message=f"Checked the first {max_claims} of {len(extracted.claims)} claims.",
        ))

    fabricated = verify_quotes([c.claim_text.quote for c in claims], text)
    if fabricated:
        notes.append(AgentNote(
            level="blocker",
            message=(f"{len(fabricated)} extracted quotation(s) are not in the "
                     "document. Discard this run."),
        ))

    for i, c in enumerate(claims):
        if not c.claim_id:
            c.claim_id = f"c{i+1}"

    distinct = len({" ".join(c.cited_as.lower().split())[:300] for c in claims})
    runlog.info(f"{len(claims)} claims across {distinct} distinct references "
                f"— {len(claims) - distinct} lookup(s) saved by caching")
    if progress:
        progress(f"checking {len(claims)} claims / {distinct} references")

    if skip_claim_checks:
        runlog.warn("claim checking is off: existence only, no model calls "
                    "per reference. Much faster, and it tells you nothing "
                    "about whether the review describes the work correctly.")
        pairs = []
        for c in claims:
            found = _cached_lookup(c.cited_as)
            ref = ReferenceCheck(
                claim_id=c.claim_id, exists=found["exists"],
                matched_title=found["matched_title"],
                matched_doi=found["matched_doi"],
                matched_year=found["matched_year"],
                match_score=found["match_score"],
                source_checked=found["source_checked"])
            pairs.append((ref, ClaimCheck(
                claim_id=c.claim_id, verdict="cannot_verify", basis="none",
                reasoning="Claim checking was disabled for this run.",
                confidence="low")))
    else:
        with runlog.stage("verify references"):
            pairs = map_reduce(
                claims,
                lambda c: _check_one(c, budget, model,
                                     skip_lookup=skip_lookups,
                                     thinking_budget=thinking_budget),
                reducer=lambda rs: rs,
                max_workers=max_workers,
                on_progress=lambda n, t: progress and progress(
                    f"references {n}/{t}"),
            )
    refs = [p[0] for p in pairs]
    checks = [p[1] for p in pairs]

    n_missing = sum(1 for r in refs if r.exists == "not_found")
    if n_missing:
        notes.append(AgentNote(
            level="warning",
            message=(f"{n_missing} reference(s) not matched in Crossref or "
                     "OpenAlex. Check these by hand before drawing any "
                     "conclusion — indexing coverage is imperfect."),
        ))
    n_unverifiable = sum(1 for c in checks if c.basis in ("metadata_only", "none"))
    if n_unverifiable:
        notes.append(AgentNote(
            level="info",
            message=(f"{n_unverifiable} claim(s) could only be checked against "
                     "metadata. Their content was NOT verified."),
        ))

    # ---- synthesis is a bonus, not the result ----------------------------
    # Everything above is the expensive part and it is already done. A failure
    # here — a wrong model id for the `deep` role, a rate limit, a timeout —
    # must not discard forty completed reference checks. Degrade, record why,
    # and return.
    coverage_gaps: list[str] = []
    critique_quality = ""
    if skip_synthesis:
        runlog.info("synthesis skipped by request", kind="tool_skipped")
        notes.append(AgentNote(
            level="info",
            message=("Coverage and critique quality were not assessed: the "
                     "synthesis pass was switched off for this run. The "
                     "reference and claim results are unaffected.")))
        critique_quality = "not assessed — the synthesis pass was disabled"
    else:
        if progress:
            progress("synthesising")
        runlog.info("synthesiser: coverage and critique quality",
                    kind="agent_turn", agent="synthesiser")
        try:
            with runlog.stage("synthesise"):
                synth = structured(
                    Synthesis, model=DEEP, system=SYNTH_SYSTEM,
                    messages=[{"role": "user", "content":
                               f"<topic_hint>{topic_hint}</topic_hint>\n"
                               f"<review>{text[:120000]}</review>\n"
                               f"<results>"
                               f"{json.dumps([r.model_dump() for r in refs])}"
                               f"</results>"}],
                    max_tokens=3000, budget=budget, temperature=0.3,
                    thinking_budget=thinking_budget,
                )
                coverage_gaps = synth.coverage_gaps
                critique_quality = synth.critique_quality
        except Exception as exc:                            # noqa: BLE001
            runlog.error(f"synthesis failed: {type(exc).__name__}: "
                         f"{str(exc)[:300]}", kind="stage_failed")
            critique_quality = (
                "Not assessed — the synthesis step failed after the reference "
                "checks completed. Every result below is still valid.")
            notes.append(AgentNote(
                level="warning",
                message=(f"The final synthesis could not run "
                         f"({type(exc).__name__}: {str(exc)[:200]}). The "
                         "per-reference results below are complete and "
                         "unaffected. This is usually the model set for the "
                         "'deep' role — check it on the Settings page.")))

    return LitReviewResult(
        document_id=document_id,
        claims=claims,
        reference_checks=refs,
        claim_checks=checks,
        coverage_gaps=coverage_gaps,
        critique_quality=critique_quality,
        fabricated_quotes=fabricated,
        malformed_references=rejected_refs,
        notes=notes,
    )

