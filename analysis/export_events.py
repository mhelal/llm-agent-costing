#!/usr/bin/env python3
"""
export_events.py -- produce the publishable call-level event file.

The live AgentSuite database holds student records, submissions, marking,
legal matters and other personal data that must never leave the machine.
The paper needs none of it. This script extracts only what the analysis
reads -- one row per realised model call, plus fallback markers -- for the
136 job ids belonging to the seven campaigns, and writes a CSV with an
explicit allow-list of fields.

Nothing here is reconstructed or inferred: every row is a stored event.

    python3 analysis/export_events.py --db /path/to/suite.db \
        --outputs data/raw --out data/events/calls.csv
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

# Only these meta fields are copied. Anything else in the event -- prompts,
# document text, claim content -- is left behind rather than filtered, so a
# new field appearing upstream cannot silently start leaking.
ALLOWED = ("provider", "model", "role", "seconds", "model_seconds",
           "input_tokens", "output_tokens", "cached", "retries",
           "stop_reason", "structured")

FIELDS = ["campaign", "job_id", "cell", "replicate", "run_state",
          "kind", "event_index"] + list(ALLOWED)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--outputs", default="data/raw")
    ap.add_argument("--out", default="data/events/calls.csv")
    a = ap.parse_args()

    if not os.path.exists(a.db):
        print(f"error: no database at {a.db}", file=sys.stderr)
        return 2
    con = sqlite3.connect(a.db)
    cur = con.cursor()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)

    written = 0
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for name, fname, keys in CAMPAIGNS:
            path = os.path.join(a.outputs, fname)
            if not os.path.exists(path):
                print(f"warning: missing {path}", file=sys.stderr)
                continue
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            for rec in raw.get("records", []):
                job = rec.get("job_id")
                if job is None:
                    continue
                cell = "/".join(str(rec["cell"][k]) for k in keys)
                # fetchall() first: reusing one cursor for a nested query
                # silently truncates the outer loop.
                rows = cur.execute(
                    "select kind, meta from job_event "
                    "where job_id=? and kind in ('llm_call','provider_fallback') "
                    "order by id", (job,)).fetchall()
                for i, (kind, meta) in enumerate(rows):
                    try:
                        m = json.loads(meta or "{}")
                    except ValueError:
                        m = {}
                    out = {"campaign": name, "job_id": job, "cell": cell,
                           "replicate": rec.get("replicate"),
                           "run_state": rec.get("state"),
                           "kind": kind, "event_index": i}
                    for k in ALLOWED:
                        out[k] = m.get(k)
                    w.writerow(out)
                    written += 1
    con.close()
    print(f"wrote {written} event rows to {a.out}")
    print("fields exported:", ", ".join(FIELDS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
