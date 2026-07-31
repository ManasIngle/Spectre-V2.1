#!/usr/bin/env python3
"""Evaluate the advisory AI market read against what actually happened.

Pulls the reads + the per-minute signal log straight from the Historical Logs API
(no CSV downloads), joins each read to the Nifty spot move over the window it was
describing, and answers three questions honestly:

  Q1  Does `directional_lean` beat a coin flip?      (expected: NO — direction is
                                                      not predictable intraday)
  Q2  Does the `regime` / effectiveness gauge actually separate
      big-move windows from quiet ones?              (expected: YES — the gauge is
                                                      the validated part, AUC 0.82)
  Q3  Does `recommendation` (TRADE / SELECTIVE / STAND_ASIDE) pick
      windows with more movement to work with?

Usage:
  LOGS_API_KEY=... python3 evaluate_ai_read.py --host http://<host>:8239 [--horizon 10]

A NULL result on Q1 is the expected, correct outcome — it confirms the read
should be used as a regime/context filter, not a directional trade trigger.
"""
import argparse, io, os, sys
import pandas as pd, numpy as np, requests


def fetch(host, key, path, params=None):
    r = requests.get(f"{host}/api/logs/{path}", headers={"X-API-Key": key},
                     params=params or {}, timeout=120)
    r.raise_for_status()
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("SPECTRE_HOST", "http://localhost:8239"))
    ap.add_argument("--key", default=os.environ.get("LOGS_API_KEY", ""))
    ap.add_argument("--horizon", type=int, default=10,
                    help="minutes forward the read is judged over (default 10 = the read cadence)")
    a = ap.parse_args()
    if not a.key:
        sys.exit("Set LOGS_API_KEY (env or --key)")

    reads = pd.read_csv(io.StringIO(fetch(a.host, a.key, "intraday_reads?format=csv").text))
    sig = pd.read_csv(io.StringIO(fetch(a.host, a.key, "signals?format=csv").text))
    print(f"reads={len(reads)}  signals={len(sig)}")

    # Only reads that actually produced LLM output are evaluable.
    reads = reads[reads["DirectionalLean"].notna()].copy()
    if reads.empty:
        sys.exit("No reads with LLM output yet — nothing to evaluate. "
                 "(If this is unexpected, check finish_reason/error in intraday_reads_full.)")
    print(f"reads with LLM output: {len(reads)}")

    # Build a spot time series from the signal log.
    sig["ts"] = pd.to_datetime(sig["Date"] + " " + sig["Time"], errors="coerce")
    sig = sig.dropna(subset=["ts", "Spot"]).sort_values("ts")
    spot = sig.set_index("ts")["Spot"].astype(float)

    reads["ts"] = pd.to_datetime(reads["Date"] + " " + reads["Time"], errors="coerce")
    reads = reads.dropna(subset=["ts"]).sort_values("ts")

    # For each read: spot at the read, and spot `horizon` minutes later (same day).
    def spot_at(t):
        w = spot.loc[:t]
        return w.iloc[-1] if len(w) else np.nan

    def spot_after(t):
        end = t + pd.Timedelta(minutes=a.horizon)
        w = spot.loc[t:end]
        if len(w) < 2 or w.index[-1].date() != t.date():
            return np.nan
        return w.iloc[-1]

    reads["spot0"] = reads["ts"].map(spot_at)
    reads["spot1"] = reads["ts"].map(spot_after)
    reads = reads.dropna(subset=["spot0", "spot1"])
    reads["move_pct"] = (reads["spot1"] - reads["spot0"]) / reads["spot0"] * 100
    reads["abs_move"] = reads["move_pct"].abs()
    if reads.empty:
        sys.exit("Could not align any read to a forward spot move.")
    print(f"evaluable reads (aligned to a {a.horizon}-min forward move): {len(reads)}\n")

    # ── Q1 — directional lean vs coin flip ────────────────────────────────
    d = reads[reads["DirectionalLean"].isin(["UP", "DOWN"])].copy()
    print("Q1  DIRECTIONAL LEAN  (expected: no edge)")
    if len(d) < 10:
        print(f"    only {len(d)} directional calls — too few to judge. Need ~50+.\n")
    else:
        d["correct"] = ((d.DirectionalLean == "UP") & (d.move_pct > 0)) | \
                       ((d.DirectionalLean == "DOWN") & (d.move_pct < 0))
        acc = d.correct.mean() * 100
        try:
            from scipy import stats
            p = stats.binomtest(int(d.correct.sum()), len(d), 0.5, alternative="greater").pvalue
            ptxt = f"binomial p={p:.3f} -> {'SIGNIFICANT' if p < 0.05 else 'not significant'}"
        except Exception:
            ptxt = "(scipy unavailable)"
        print(f"    {int(d.correct.sum())}/{len(d)} = {acc:.1f}%   {ptxt}")
        signed = np.where(d.DirectionalLean == "UP", 1, -1) * d.move_pct
        print(f"    mean signed move if followed: {signed.mean():+.4f}%  "
              f"(needs to clear option costs to matter)")
        for conf in ["low", "medium", "high"]:
            s = d[d.LeanConfidence == conf]
            if len(s) >= 5:
                print(f"      conf={conf:6s} n={len(s):3d} acc={s.correct.mean()*100:.1f}%")
        print()

    # ── Q2 — does the regime gauge separate movement? ─────────────────────
    print("Q2  REGIME vs REALISED MOVEMENT  (expected: ACTIVE > NORMAL > DEAD)")
    g = reads.groupby("Regime")["abs_move"].agg(["count", "mean", "median"])
    for reg in ["ACTIVE", "NORMAL", "DEAD"]:
        if reg in g.index:
            r = g.loc[reg]
            print(f"    {reg:7s} n={int(r['count']):3d}  mean|move|={r['mean']:.3f}%  median={r['median']:.3f}%")
    if {"ACTIVE", "DEAD"} <= set(g.index):
        ratio = g.loc["ACTIVE", "mean"] / max(g.loc["DEAD", "mean"], 1e-9)
        print(f"    ACTIVE/DEAD movement ratio: {ratio:.2f}x  "
              f"({'gauge is working' if ratio > 1.3 else 'gauge NOT separating — investigate'})")
    print()

    # ── Q3 — recommendation vs movement ───────────────────────────────────
    print("Q3  RECOMMENDATION vs REALISED MOVEMENT")
    for rec in ["TRADE", "SELECTIVE", "STAND_ASIDE"]:
        s = reads[reads["Recommendation"] == rec]
        if len(s):
            print(f"    {rec:12s} n={len(s):3d}  mean|move|={s.abs_move.mean():.3f}%")
    print()
    print("Reminder: a null Q1 with a positive Q2 is the EXPECTED result and means "
          "the read should gate engage/stand-aside, not direction.")


if __name__ == "__main__":
    main()
