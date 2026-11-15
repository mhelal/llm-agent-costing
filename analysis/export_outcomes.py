#!/usr/bin/env python3
"""
export_outcomes.py -- one row per attempted run, with why it ended.

The paper states why the unsuccessful runs failed. That claim needs an
artefact behind it, so this classifies each run from its own terminal event
and writes the result alongside the call-level export. Classification is by
event kind and terminal message, never by guesswork: anything that does not
match a known pattern is written out as "unclassified" rather than forced
into a bucket.

    python3 analysis/export_outcomes.py --db /path/to/suite.db \
        --outputs data/raw --out data/events/run_outcomes.csv
"""
from __future__ import annotations
import argparse, csv, json, os, sqlite3, sys

CAMPAIGNS = [
    ("Partitioning A", "partitioning_v20_20260828_034749_raw.json", ("window", "workers")),
    ("Partitioning B", "partitioning_v21_20260831_050830_raw.json", ("window", "workers")),
    ("Role sizing A",  "role_sizing_v1_20260825_134042_raw.json",   ("mid_model",)),
    ("Role sizing B",  "role_sizing_v11_20260831_112252_raw.json",  ("mid_model",)),
    ("Fan-out A",      "fan_out_v1_20260824_222008_raw.json",       ("workers",)),
    ("Fan-out B",      "fan_out_v2_20260829_142226_raw.json",       ("workers",)),
    ("Protocol",       "protocol_v10_20260831_151050_raw.json",     ("critic_rounds",)),
]

FIELDS = ["campaign", "job_id", "cell", "replicate", "state", "seconds",
          "llm_calls", "cause", "started_utc", "ended_utc", "cause_utc",
          "detail"]


def classify(kinds: set, message: str) -> tuple[str, str]:
    """Return (cause, short detail). Unrecognised endings stay unclassified."""
    if "preflight_failed" in kinds:
        return ("preflight_refused",
                "configured endpoint unusable; no model call attempted")
    if "no parseable output" in message or "prose rather than JSON" in message:
        return ("all_windows_unparseable", "no window produced valid JSON")
    if "No claims were extracted" in message:
        return ("empty_result_guard", "zero claims from a document with citations")
    if "workers failed" in message:
        return ("all_workers_failed", "every fan-out worker raised")
    if "stage_failed" in kinds and not message:
        return ("stage_failed_no_message", "stage raised without a terminal record")
    return ("unclassified", message[:80])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--outputs", default="data/raw")
    ap.add_argument("--out", default="data/events/run_outcomes.csv")
    a = ap.parse_args()
    if not os.path.exists(a.db):
        print(f"error: no database at {a.db}", file=sys.stderr)
        return 2
    con = sqlite3.connect(a.db)
    cur = con.cursor()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    n = 0
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for name, fname, keys in CAMPAIGNS:
            p = os.path.join(a.outputs, fname)
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
            for rec in raw.get("records", []):
                j = rec.get("job_id")
                if j is None:
                    continue
                kinds = {k for (k,) in cur.execute(
                    "select distinct kind from job_event where job_id=?", (j,)).fetchall()}
                row = cur.execute(
                    "select message from job_event where job_id=? and kind='job_failed' "
                    "order by id desc limit 1", (j,)).fetchone()
                msg = row[0] if row else ""
                lo, hi = cur.execute(
                    "select min(ts), max(ts) from job_event where job_id=?", (j,)).fetchone()
                calls = cur.execute(
                    "select count(*) from job_event where job_id=? and kind='llm_call'",
                    (j,)).fetchone()[0]
                if rec.get("state") == "done":
                    cause, detail, cause_ts = "completed", "", None
                else:
                    cause, detail = classify(kinds, msg)
                    # When the failure was RECORDED, which is not when the job
                    # started: a preflight refusal fires a second or two in.
                    # Claims about outage timing must use this, not job start.
                    probe = ("preflight_failed" if "preflight_failed" in kinds
                             else "job_failed")
                    row2 = cur.execute(
                        "select ts from job_event where job_id=? and kind=? "
                        "order by id limit 1", (j, probe)).fetchone()
                    cause_ts = row2[0] if row2 else hi
                w.writerow({
                    "campaign": name, "job_id": j,
                    "cell": "/".join(str(rec["cell"][k]) for k in keys),
                    "replicate": rec.get("replicate"), "state": rec.get("state"),
                    "seconds": rec.get("seconds"), "llm_calls": calls,
                    "cause": cause,
                    "started_utc": lo, "ended_utc": hi,
                    "cause_utc": cause_ts, "detail": detail})
                n += 1
    con.close()
    print(f"wrote {n} run outcomes to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
