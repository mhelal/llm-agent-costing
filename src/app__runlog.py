# Verbatim excerpt from app/runlog.py of AgentSuite.
# The event record every provenance claim in the paper is derived from.
#
# This is a READING COPY, not a runnable module. Line numbers refer to
# the original file so each excerpt can be checked against the source.

# ---- app/runlog.py:65-81 ----
def event(level: str, message: str, *, kind: str = "note", **meta: Any) -> None:
    """Record one thing that happened. Never raises — logging must not break a run."""
    job_id = _job_id.get()
    if job_id is None:
        return
    try:
        from .db import tx

        with tx() as con:
            con.execute(
                "INSERT INTO job_event (job_id, ts, level, stage, kind, "
                "message, meta) VALUES (?,?,?,?,?,?,?)",
                (job_id, time.time(), level, _stage.get(), kind,
                 message[:1000], json.dumps(meta, default=str)[:2000]),
            )
    except Exception:                                       # noqa: BLE001
        pass

