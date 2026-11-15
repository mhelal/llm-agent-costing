#!/usr/bin/env python3
"""
check_paper_consistency.py -- assert that every number quoted in the paper
is reproduced by the stored data.

This exists because the paper and the data are maintained separately, and a
late edit to either can silently put them out of step. Each check recomputes
a value from data/raw and data/events, formats it exactly as the paper
writes it, and asserts that string is present in the .tex. A failure means
one of the two is wrong -- the checker does not guess which.

    python3 analysis/check_paper_consistency.py \
        --tex paper/agentsCosting_camera.tex \
        --raw data/raw --events data/events/calls.csv

Exit status is non-zero if any check fails, so it can gate a commit.
"""
from __future__ import annotations
import argparse, csv, json, os, re, statistics as st, sys
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
LOCAL = {"ollama"}

PASS, FAIL = [], []


def check(label: str, needle: str, tex: str, note: str = "") -> None:
    """Assert `needle` appears in the paper. `needle` is computed from data."""
    if needle in tex:
        PASS.append((label, needle))
    else:
        FAIL.append((label, needle, note))


def load_raw(rawdir):
    out = {}
    for name, fname, keys in CAMPAIGNS:
        p = os.path.join(rawdir, fname)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                out[name] = (json.load(f), keys)
    return out


def load_events(path):
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return rows


def mean_ok(records, key="seconds"):
    v = [r[key] for r in records if r.get("state") == "done" and r.get(key) is not None]
    if not v:
        return None, None, 0
    return st.mean(v), (st.stdev(v) if len(v) > 1 else 0.0), len(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tex", default="paper/agentsCosting_camera.tex")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--events", default="data/events/calls.csv")
    a = ap.parse_args()

    tex = open(a.tex, encoding="utf-8").read()
    # Collapse whitespace so a line break in the .tex never breaks a match.
    flat = re.sub(r"\s+", " ", tex)
    raws = load_raw(a.raw)
    events = load_events(a.events)
    if not raws or not events:
        print("error: missing data/raw or data/events", file=sys.stderr)
        return 2

    # ---- 1. inventory -----------------------------------------------------
    att = sum(c["runs"] for _, (r, _) in raws.items() for c in r["cells"])
    fail = sum(c["failures"] for _, (r, _) in raws.items() for c in r["cells"])
    conds = sum(len(r["cells"]) for _, (r, _) in raws.items())
    calls = [e for e in events if e["kind"] == "llm_call"]
    fbs = [e for e in events if e["kind"] == "provider_fallback"]
    N = len(calls)
    L = sum(1 for e in calls if (e["provider"] or "").lower() in LOCAL)
    H = N - L

    check("attempts", str(att), flat)
    check("successes", str(att - fail), flat)
    check("failures", str(fail), flat)
    check("conditions", str(conds), flat)
    check("realised calls", f"{N:,}".replace(",", "{,}"), flat)
    check("hosted calls", f"{H:,}".replace(",", "{,}"), flat)
    check("hosted pct", f"{100*H/N:.1f}", flat)
    check("local count", str(L), flat)
    check("local pct", f"{100*L/N:.1f}", flat)
    check("fallback count", str(len(fbs)), flat)
    check("deliberate-local count", str(L - len(fbs)), flat)
    check("distinct realised models",
          {"6": "Six", "5": "Five", "7": "Seven"}.get(
              str(len({e["model"] for e in calls})), "?"), flat,
          "paper spells this as a word")

    # per-campaign call counts in Table I
    percamp = Counter(e["campaign"] for e in calls)
    for name, _, _ in CAMPAIGNS:
        check(f"Table I calls: {name}", str(percamp[name]), flat)

    # ---- 2. fallback by window, at the paper's granularity ----------------
    # The paper quotes a range over individual window/worker CELLS, not over
    # window sizes. Aggregating differently gives a different range and looks
    # like a contradiction, so match the paper's unit exactly.
    cellpct, k28 = [], 0
    for name in ("Partitioning A", "Partitioning B"):
        byc = defaultdict(lambda: [0, 0])
        for e in calls:
            if e["campaign"] != name:
                continue
            w = e["cell"].split("/")[0]
            byc[e["cell"]][0] += 1
            if (e["provider"] or "").lower() in LOCAL:
                byc[e["cell"]][1] += 1
        for cell, (tot, loc) in byc.items():
            pct = 100 * loc / tot if tot else 0.0
            if cell.startswith("28000"):
                k28 += loc
            else:
                cellpct.append(pct)
    check("fallback range low", f"{min(cellpct):.1f}", flat)
    check("fallback range high", f"{max(cellpct):.1f}", flat)
    if k28 == 0:
        PASS.append(("28k has zero local calls", "0 verified"))
    else:
        FAIL.append(("28k has zero local calls", f"found {k28}", "paper claims zero"))

    # ---- 3. Ev table (campaign A) and fan-out ------------------------------
    rawA, keysA = raws["Partitioning A"]
    recs = defaultdict(list)
    for r in rawA["records"]:
        recs["/".join(str(r["cell"][k]) for k in keysA)].append(r)
    evs = {}
    for c in rawA["cells"]:
        k = "/".join(str(c["cell"][x]) for x in keysA)
        T, sd, n = mean_ok(recs[k])
        Nc = (c.get("claims_extracted") or {}).get("mean")
        V = (c.get("quality") or {}).get("verbatim_rate")
        if T is None or not Nc or not V:
            continue
        evs[k] = T / (Nc * V)
        check(f"Ev table T {k}", f"{T:.1f}", flat)
        check(f"Ev table Ev {k}", f"{T/(Nc*V):.2f}", flat)
    best = min(evs, key=evs.get)
    check("Ev minimum value", f"{evs[best]:.2f}", flat)

    for camp in ("Fan-out A", "Fan-out B"):
        raw, keys = raws[camp]
        rr = defaultdict(list)
        for r in raw["records"]:
            rr[str(r["cell"]["workers"])].append(r)
        base = None
        for w in ("1", "2", "4"):
            T, sd, n = mean_ok(rr[w])
            if T is None:
                continue
            if w == "1":
                base = T
            check(f"{camp} w={w} mean", f"{T:.2f}", flat)
            if w == "2" and base:
                check(f"{camp} 1->2 reduction", f"{100*(base-T)/base:.1f}", flat)

    # ---- 4. things the paper states that the data must not contradict -----
    protocol_agent = raws["Protocol"][0]["spec"].get("agent")
    extract_agents = {raws[n][0]["spec"].get("agent")
                      for n, _, _ in CAMPAIGNS if n != "Protocol"}
    if protocol_agent not in extract_agents:
        PASS.append(("protocol uses a different agent",
                     f"{protocol_agent} vs {sorted(extract_agents)}"))
    else:
        FAIL.append(("protocol uses a different agent", protocol_agent,
                     "paper says it is a different task family"))

    docs = {i.get("document_id") for n, _, _ in CAMPAIGNS
            for i in raws[n][0]["spec"].get("inputs", []) if "document_id" in i}
    if len(docs) == 2:
        PASS.append(("two source documents", str(sorted(docs))))
    else:
        FAIL.append(("two source documents", str(sorted(docs)), "paper says two"))

    # ---- report -----------------------------------------------------------
    print("=" * 72)
    print("PAPER / DATA CONSISTENCY")
    print("=" * 72)
    for label, needle in PASS:
        print(f"  PASS  {label:<38} {needle}")
    for label, needle, note in FAIL:
        print(f"  FAIL  {label:<38} computed {needle!r} not found in .tex"
              + (f"  ({note})" if note else ""))
    print("-" * 72)
    print(f"  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("\n  A failure means the paper and the data disagree.")
        print("  Fix whichever is wrong; do not adjust this checker to match.")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
