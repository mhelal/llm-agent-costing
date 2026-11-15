#!/usr/bin/env python3
"""
verify_paper_claims.py — regenerate every number quoted in the paper
from the raw campaign files plus the exported call-level event log.

    python3 analysis/verify_paper_claims.py

Reads data/raw/*.json and data/events/calls.csv, both of which ship with
this repository. The application database is NOT required and is not
published: it holds personal records that no claim in the paper depends on.
Pass --db to read a live database directly instead of the CSV export.

Nothing here calls a model. Every figure is recomputed from stored
measurements, so the output is a check on the paper, not a new experiment.
"""
from __future__ import annotations
import argparse, csv, json, os, sqlite3, statistics as st, sys
from collections import Counter, defaultdict

CAMPAIGNS = [
    ("Partitioning A", "partitioning_v20_20260828_034749_raw.json", ("window", "workers")),
    ("Partitioning B", "partitioning_v21_20260831_050830_raw.json", ("window", "workers")),
    ("Role sizing A",  "role_sizing_v1_20260825_134042_raw.json",   ("mid_model",)),
    ("Role sizing B",  "role_sizing_v11_20260831_112252_raw.json",  ("mid_model",)),
    ("Fan-out A",      "fan_out_v1_20260824_222008_raw.json",       ("workers",)),
    ("Fan-out B",      "fan_out_v2_20260829_142226_raw.json",       ("workers",)),
    ("Protocol",       "protocol_v10_20260831_151050_raw.json",     ("critic_rounds",)),
]
LOCAL_PROVIDERS = {"ollama"}


def load(outputs, fname):
    with open(os.path.join(outputs, fname), encoding="utf-8") as fh:
        return json.load(fh)


class Events:
    """Call-level events, from the shipped CSV or a live database.

    Both paths return the same shape, so the rest of the script does not
    know or care which was used.
    """

    def __init__(self, csv_path=None, db_path=None):
        self.by_job = defaultdict(list)
        if db_path:
            con = sqlite3.connect(db_path)
            cur = con.cursor()
            rows = cur.execute(
                "select job_id, kind, meta from job_event "
                "where kind in ('llm_call','provider_fallback')").fetchall()
            con.close()
            for job, kind, meta in rows:
                try:
                    m = json.loads(meta or "{}")
                except ValueError:
                    m = {}
                self.by_job[job].append({"kind": kind,
                                         "provider": m.get("provider")})
            self.source = f"database {db_path}"
        else:
            with open(csv_path, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    self.by_job[int(r["job_id"])].append(
                        {"kind": r["kind"], "provider": r["provider"]})
            self.source = f"event export {csv_path}"

    def mix(self, jobs):
        """Realised provider mix and fallback count for a set of job ids."""
        m, fb = Counter(), 0
        for j in jobs:
            for e in self.by_job.get(j, []):
                if e["kind"] == "provider_fallback":
                    fb += 1
                else:
                    m[(e["provider"] or "?").lower()] += 1
        return m, fb


def mean_ok(records, key="seconds"):
    """Mean over SUCCESSFUL runs only.

    The stored cell aggregate for `seconds` averages every attempt, including
    runs that aborted early. An aborted run is short, so including it pulls a
    cell's mean latency DOWN -- it makes a fragile configuration look fast.
    Quality aggregates already exclude failures; timing did not.
    """
    vals = [r[key] for r in records
            if r.get("state") == "done" and r.get(key) is not None]
    if not vals:
        return None, None, 0
    return (st.mean(vals),
            st.stdev(vals) if len(vals) > 1 else 0.0,
            len(vals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", default="data/raw")
    ap.add_argument("--events", default="data/events/calls.csv")
    ap.add_argument("--db", default=None,
                    help="read a live database instead of the CSV export")
    a = ap.parse_args()
    if a.db:
        ev = Events(db_path=a.db)
    elif os.path.exists(a.events):
        ev = Events(csv_path=a.events)
    else:
        print(f"error: no events at {a.events} and no --db given", file=sys.stderr)
        return 2
    print(f"source: {ev.source}\n")

    total = Counter()
    att = fail = conds = fb_all = 0

    print("=" * 74)
    print("1. INVENTORY AND REALISED PROVENANCE")
    print("=" * 74)
    print(f"{'Campaign':<16}{'cond':>5}{'att':>5}{'fail':>5}{'calls':>7}"
          f"{'hosted':>8}{'local':>7}{'fallbk':>8}")
    for name, fname, _ in CAMPAIGNS:
        raw = load(a.outputs, fname)
        jobs = [r["job_id"] for r in raw.get("records", []) if r.get("job_id")]
        mix, fb = ev.mix(jobs)
        n = sum(mix.values())
        loc = sum(v for k, v in mix.items() if k in LOCAL_PROVIDERS)
        c = len(raw["cells"])
        at = sum(x["runs"] for x in raw["cells"])
        fl = sum(x["failures"] for x in raw["cells"])
        conds += c; att += at; fail += fl; fb_all += fb
        total.update(mix)
        print(f"{name:<16}{c:>5}{at:>5}{fl:>5}{n:>7}{n-loc:>8}{loc:>7}{fb:>8}")
    N = sum(total.values())
    L = sum(v for k, v in total.items() if k in LOCAL_PROVIDERS)
    print(f"{'TOTAL':<16}{conds:>5}{att:>5}{fail:>5}{N:>7}{N-L:>8}{L:>7}{fb_all:>8}")
    print(f"\n  PAPER: {N} realised calls; hosted {N-L} ({100*(N-L)/N:.1f}%); "
          f"local {L} ({100*L/N:.1f}%)")
    print(f"  of the {L} local calls, {fb_all} were mid-run fallback and "
          f"{L-fb_all} a deliberately local campaign")

    print("\n" + "=" * 74)
    print("2. 28k IS NOT A FALLBACK ARTEFACT  (fallback per window/worker cell)")
    print("=" * 74)
    print("   Reported per CELL, which is the unit the paper quotes. Pooling by")
    print("   window size instead gives a different range for the same data.")
    non28, n28local = [], 0
    for name, fname, keys in CAMPAIGNS[:2]:
        raw = load(a.outputs, fname)
        byc = {}
        for r in raw["records"]:
            k = f"{r['cell']['window']}/{r['cell']['workers']}"
            byc.setdefault(k, []).append(r["job_id"])
        print(f"\n  {name}")
        for k in sorted(byc, key=lambda x: (int(x.split("/")[0]), int(x.split("/")[1]))):
            mix, fb = ev.mix(byc[k])
            n = sum(mix.values())
            loc = sum(v for p_, v in mix.items() if p_ in LOCAL_PROVIDERS)
            pct = 100 * loc / n if n else 0.0
            if k.startswith("28000"):
                n28local += loc
            else:
                non28.append(pct)
            print(f"    cell={k:<10} calls={n:<4} local={loc:<3} ({pct:5.1f}%)  fallback={fb}")
    print(f"\n  PAPER: fallback ran at {min(non28):.1f}-{max(non28):.1f}% of calls in the "
          f"6k and 14k cells")
    print(f"         and in exactly {n28local} calls across every 28k cell of both campaigns.")

    print("\n" + "=" * 74)
    print("3. TIMING MEANS: ALL ATTEMPTS vs SUCCESSFUL RUNS ONLY")
    print("=" * 74)
    for name, fname, keys in CAMPAIGNS:
        raw = load(a.outputs, fname)
        cells = {}
        for r in raw["records"]:
            cells.setdefault(tuple(str(r["cell"][k]) for k in keys), []).append(r)
        shown = False
        for k, recs in cells.items():
            allv = [r["seconds"] for r in recs if r.get("seconds") is not None]
            mA = st.mean(allv) if allv else float("nan")
            mO, sdO, nO = mean_ok(recs)
            if mO is not None and abs(mA - mO) > 0.05:
                if not shown:
                    print(f"\n  {name}"); shown = True
                print(f"    {'/'.join(k)[:30]:<30} reported={mA:8.2f}  "
                      f"successes-only={mO:8.2f} (sd {sdO:6.2f}, n={nO})")
        if not shown:
            print(f"\n  {name}: no difference (no failures)")

    print("\n" + "=" * 74)
    print("4. OPERATING POINTS  Ev = T / (Nc * V)")
    print("=" * 74)
    for name, fname, keys in CAMPAIGNS:
        raw = load(a.outputs, fname)
        recs = {}
        for r in raw["records"]:
            recs.setdefault(tuple(str(r["cell"][k]) for k in keys), []).append(r)
        print(f"\n  {name}")
        for c in raw["cells"]:
            k = tuple(str(c["cell"][x]) for x in keys)
            label = "/".join(k)[:34]
            T, sd, n = mean_ok(recs.get(k, []))
            if T is None:
                # A cell where every attempt failed has no quality aggregate
                # at all -- not a zero, an absent key. Report the attempts so
                # the failure stays visible instead of vanishing from the table.
                print(f"    {label:<34} 0/{c.get('runs', '?')} successful runs "
                      f"-- no quality aggregate recorded")
                continue
            ce = c.get("claims_extracted")
            Nc = ce.get("mean") if isinstance(ce, dict) else None
            q = c.get("quality") or {}
            V = q.get("verbatim_rate")
            if Nc is None and V is None:
                # Not a failure: this campaign runs a different agent on a
                # different task, which reports agreement rather than
                # extraction. Ev is undefined by construction, not by error.
                print(f"    {label:<34} n={n} T={T:8.2f} (sd {sd:6.2f}) "
                      f"[assessment task: Ev not applicable] "
                      f"recall={q.get('pooled_recall')} "
                      f"corrob={q.get('corroborated_rate')} "
                      f"stability={q.get('stability')}")
                continue
            ev = T / (Nc * V) if (Nc and V) else None
            nc_s = f"{Nc:6.1f}" if Nc is not None else "     ?"
            v_s = f"{V:.3f}" if V is not None else "    ?"
            ev_s = f"{ev:7.2f}" if ev else "  undef"
            print(f"    {label:<34} n={n} T={T:8.2f} (sd {sd:6.2f}) "
                  f"Nc={nc_s} V={v_s} Ev={ev_s}")


if __name__ == "__main__":
    main()
