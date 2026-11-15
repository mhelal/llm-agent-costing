# Verbatim excerpt from app/orchestrator.py of AgentSuite.
# The coordination primitives. map_reduce is what the fan-out factor varies.
#
# This is a READING COPY, not a runnable module. Line numbers refer to
# the original file so each excerpt can be checked against the source.

# ---- app/orchestrator.py:40-86 ----
def map_reduce(
    items: Iterable[T],
    worker: Callable[[T], R],
    reducer: Callable[[list[R]], Any],
    *,
    max_workers: int = 4,
    on_progress: Optional[Callable[[int, int], None]] = None,
    tolerate_failures: bool = True,
) -> Any:
    """Fan out to independent workers, then synthesise.

    `max_workers` is small by default because on shared hosting the process
    monitor kills whoever tips the account over its memory limit, and eight
    concurrent HTTPS clients will do that. Raise it on a VPS.
    """
    items = list(items)
    results: list[R] = []
    failures: list[tuple[T, Exception]] = []

    # ThreadPoolExecutor does not carry contextvars into its threads, so the
    # run log's job binding would be lost and every event from a fan-out
    # worker silently dropped — exactly the part of a run you most want to
    # watch. Copy the context per task.
    from . import runlog

    with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(runlog.copy_context().run, worker, it): it
                   for it in items}
        for n, fut in enumerate(cf.as_completed(futures), start=1):
            try:
                results.append(fut.result())
            except Exception as exc:                       # noqa: BLE001
                if not tolerate_failures:
                    raise
                failures.append((futures[fut], exc))
                runlog.error(f"worker failed: {type(exc).__name__}: "
                             f"{str(exc)[:150]}", kind="worker_failed")
                log.exception("worker failed on %r", futures[fut])
            if on_progress:
                on_progress(n, len(items))

    if failures:
        runlog.warn(f"{len(failures)} of {len(items)} workers failed; "
                    f"continuing with {len(results)}", kind="partial_failure")
    if failures and not results:
        raise RuntimeError(f"all {len(failures)} workers failed: {failures[0][1]}")
    return reducer(results)

# ---- app/orchestrator.py:89-115 ----
def critic_loop(
    generate: Callable[[Optional[str]], T],
    critique: Callable[[T], tuple[bool, str]],
    *,
    max_rounds: int = 3,
    on_round: Optional[Callable[[int, bool, str], None]] = None,
) -> tuple[T, list[str]]:
    """Generator/critic with a bounded number of revisions.

    `critique` returns (accepted, feedback). The bound matters: without it a
    fastidious critic and an obliging generator will revise forever, and the
    third revision is almost never better than the second.
    """
    feedback: Optional[str] = None
    history: list[str] = []
    draft = generate(None)

    for rnd in range(max_rounds):
        accepted, feedback = critique(draft)
        history.append(feedback)
        if on_round:
            on_round(rnd, accepted, feedback)
        if accepted:
            return draft, history
        draft = generate(feedback)

    return draft, history

# ---- app/orchestrator.py:26-37 ----
def pipeline(value: Any, stages: Sequence[Callable[[Any], Any]],
             on_stage: Optional[Callable[[int, str], None]] = None) -> Any:
    """Sequential composition. Use when the steps are known in advance.

    Which is most of the time. A pipeline is cheaper, reproducible and
    debuggable; reach for map_reduce or a loop only when it genuinely fails.
    """
    for i, stage in enumerate(stages):
        if on_stage:
            on_stage(i, getattr(stage, "__name__", f"stage{i}"))
        value = stage(value)
    return value

