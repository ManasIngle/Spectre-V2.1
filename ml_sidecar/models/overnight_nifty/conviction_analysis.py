"""
Conviction-only filter analysis for the XGBoost direction model.

Premise: the model's average accuracy is mediocre, but maybe accuracy is
*much higher* on the subset of days where it's confident. If so, we can trade
only those days and still extract edge.

We re-run the walk-forward XGB and, for each fold, measure accuracy at
different probability thresholds (0.40, 0.45, 0.50, 0.55, 0.60). Output:
  • Per-threshold accuracy + trade frequency
  • The threshold's break-even cost: net edge per trade after typical 0.05% slippage

Plus an "Asia agreement" filter: only trade when prediction direction matches
the sign of overnight KOSPI + HSI returns (or 2 of 3 with Nikkei).
"""
from __future__ import annotations

import io
import os
import sys

import joblib
import numpy as np
import pandas as pd

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import xgboost as xgb

from feature_engineering import DIR_LABELS, build_features, split_features_targets
from train_xgb_direction import (
    FOLD_BOUNDARIES, _bal_sample_weights, make_xgb,
)

THIS_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(THIS_DIR, "data")
RAW_PATH = os.path.join(DATA_DIR, "overnight_raw.parquet")
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
OUT_DIR = os.path.join(REPO_ROOT, "backtest", "overnight_lstm_holdout")
os.makedirs(OUT_DIR, exist_ok=True)


def collect_walkforward_predictions() -> pd.DataFrame:
    """Re-run XGB walk-forward and return a concatenated predictions frame
    with: date, fold, actual_dir, pred_dir, p_down, p_flat, p_up, plus the
    Asia overnight signs (kospi_ret_1, hsi_ret_1, nikkei_ret_1) for filtering."""
    raw = pd.read_parquet(RAW_PATH)
    feats = build_features(raw)
    feat_cols, _, _ = split_features_targets(feats)
    X = feats[feat_cols].values.astype(np.float32)
    y = feats["y_dir"].values.astype(np.int64)
    dates = feats.index

    asia_cols = ["kospi_ret_1", "hsi_ret_1", "nikkei_ret_1"]
    asia_idx = [feat_cols.index(c) for c in asia_cols]

    out = []
    for i, (start, end) in enumerate(FOLD_BOUNDARIES, 1):
        ts_start, ts_end = pd.Timestamp(start), pd.Timestamp(end)
        train_mask = dates < ts_start
        test_mask = (dates >= ts_start) & (dates <= ts_end)
        if train_mask.sum() < 200 or test_mask.sum() < 30:
            continue
        sw = _bal_sample_weights(y[train_mask])
        model = make_xgb()
        model.fit(X[train_mask], y[train_mask], sample_weight=sw, verbose=False)
        proba = model.predict_proba(X[test_mask])
        pred = np.argmax(proba, axis=1)
        df = pd.DataFrame({
            "date": dates[test_mask],
            "fold": i,
            "actual_dir": y[test_mask],
            "pred_dir": pred,
            "p_down": proba[:, 0],
            "p_flat": proba[:, 1],
            "p_up":   proba[:, 2],
            "kospi_ret_1": X[test_mask, asia_idx[0]],
            "hsi_ret_1":   X[test_mask, asia_idx[1]],
            "nikkei_ret_1": X[test_mask, asia_idx[2]],
        })
        out.append(df)
    return pd.concat(out, ignore_index=True)


def conviction_table(preds: pd.DataFrame) -> pd.DataFrame:
    """For each prob threshold, measure trade frequency and accuracy."""
    rows = []
    total = len(preds)
    p_top = preds[["p_down", "p_flat", "p_up"]].max(axis=1).values
    for thr in [0.0, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:  # 'thr' = confidence threshold
        keep = (p_top >= thr) & (preds["pred_dir"] != 1)  # ignore FLAT preds
        n = int(keep.sum())
        if n == 0:
            rows.append({"threshold": thr, "trades": 0, "trade_freq_pct": 0.0,
                          "directional_acc_pct": float("nan")})
            continue
        sub = preds[keep]
        acc = float((sub["pred_dir"] == sub["actual_dir"]).mean())
        rows.append({
            "threshold": thr,
            "trades": n,
            "trade_freq_pct": round(n / total * 100, 1),
            "directional_acc_pct": round(acc * 100, 1),
        })
    return pd.DataFrame(rows)


def asia_agreement_table(preds: pd.DataFrame) -> pd.DataFrame:
    """Filter to days where Asia overnight (Kospi+HSI+Nikkei) agrees with prediction."""
    pred_sign = preds["pred_dir"].map({0: -1, 1: 0, 2: 1}).values
    asia_signs = np.sign(preds[["kospi_ret_1", "hsi_ret_1", "nikkei_ret_1"]].values)
    # Number of asia indices matching prediction sign (skip 0s)
    matches = ((asia_signs == pred_sign[:, None]) & (asia_signs != 0)).sum(axis=1)
    rows = []
    total = len(preds)
    for k in [0, 1, 2, 3]:
        keep = (matches >= k) & (preds["pred_dir"] != 1)
        n = int(keep.sum())
        if n == 0:
            rows.append({"min_asia_agree": k, "trades": 0, "trade_freq_pct": 0.0,
                          "directional_acc_pct": float("nan")})
            continue
        sub = preds[keep]
        acc = float((sub["pred_dir"] == sub["actual_dir"]).mean())
        rows.append({
            "min_asia_agree": k,
            "trades": n,
            "trade_freq_pct": round(n / total * 100, 1),
            "directional_acc_pct": round(acc * 100, 1),
        })
    return pd.DataFrame(rows)


def combined_filter_table(preds: pd.DataFrame) -> pd.DataFrame:
    """Cross-tab: probability threshold × min asia agreement."""
    pred_sign = preds["pred_dir"].map({0: -1, 1: 0, 2: 1}).values
    asia_signs = np.sign(preds[["kospi_ret_1", "hsi_ret_1", "nikkei_ret_1"]].values)
    matches = ((asia_signs == pred_sign[:, None]) & (asia_signs != 0)).sum(axis=1)
    p_top = preds[["p_down", "p_flat", "p_up"]].max(axis=1).values

    rows = []
    for thr in [0.45, 0.50, 0.55]:
        for k in [1, 2]:
            keep = (p_top >= thr) & (matches >= k) & (preds["pred_dir"] != 1)
            n = int(keep.sum())
            sub = preds[keep]
            acc = float((sub["pred_dir"] == sub["actual_dir"]).mean()) if n else float("nan")
            rows.append({
                "prob_threshold": thr,
                "min_asia_agree": k,
                "trades": n,
                "trade_freq_pct": round(n / len(preds) * 100, 1),
                "directional_acc_pct": round(acc * 100, 1) if n else None,
            })
    return pd.DataFrame(rows)


def main():
    print("Re-running XGB walk-forward to collect predictions for filtering analysis…")
    preds = collect_walkforward_predictions()
    print(f"Total walk-forward predictions: {len(preds)}")

    print("\n=== Conviction (probability threshold) ===")
    conv = conviction_table(preds)
    print(conv.to_string(index=False))

    print("\n=== Asia overnight agreement filter ===")
    asia = asia_agreement_table(preds)
    print(asia.to_string(index=False))

    print("\n=== Combined (prob threshold × Asia agreement) ===")
    comb = combined_filter_table(preds)
    print(comb.to_string(index=False))

    md = ["# Conviction-only filter analysis (XGBoost walk-forward)\n\n"]
    md.append("This evaluates whether the XGBoost direction model has higher accuracy on a *subset* of days where it is confident or where Asia overnight cues agree with its prediction. If so, conviction-only trading can extract edge from a model that's mediocre on average.\n\n")
    md.append(f"Total walk-forward UP/DOWN predictions across 2021-2025: **{len(preds)}**\n\n")
    md.append("## 1. Probability threshold filter\n\n")
    md.append("Trade only when the model's top-class probability is ≥ threshold.\n\n")
    md.append(conv.to_markdown(index=False)); md.append("\n\n")
    md.append("## 2. Asia agreement filter\n\n")
    md.append("Trade only when at least K of {KOSPI, HSI, Nikkei} overnight returns share the same sign as the predicted direction.\n\n")
    md.append(asia.to_markdown(index=False)); md.append("\n\n")
    md.append("## 3. Combined filter\n\n")
    md.append(comb.to_markdown(index=False)); md.append("\n\n")
    md.append("## Notes\n\n")
    md.append("- Coin-flip baseline = 50% on directional preds.\n")
    md.append("- After typical Indian retail costs (brokerage + slippage on Nifty options ≈ 0.05-0.15% per trade), break-even directional accuracy is ~52-55%.\n")
    md.append("- A filter is useful if it raises directional accuracy above ~55% while keeping trade count ≥ ~30/year.\n")

    md_path = os.path.join(OUT_DIR, "conviction_analysis.md")
    with open(md_path, "w") as f:
        f.writelines(md)
    print(f"\nSaved: {md_path}")


if __name__ == "__main__":
    main()
