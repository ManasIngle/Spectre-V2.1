"""
v3 — XGBoost regression model for predicted next-day close (in ₹).

Predicts log-return (scaled to %), derives close. Walk-forward evaluation
matches the direction model so we can report MAE / RMSE on the same folds.

This pairs with stacked_v3_* (direction). The combined inference script
returns both: predicted close (this model) + direction & confidence (stacked).

Output:
  • Per-fold MAE/RMSE → backtest/overnight_lstm_holdout/v3_regression_report.md
  • Final model       → overnight_nifty/regression_v3_xgb.pkl
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from feature_engineering import build_features, split_features_targets

THIS_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(THIS_DIR, "data")
RAW_PATH = os.path.join(DATA_DIR, "overnight_raw.parquet")
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
OUT_DIR = os.path.join(REPO_ROOT, "backtest", "overnight_lstm_holdout")
os.makedirs(OUT_DIR, exist_ok=True)

REG_PATH = os.path.join(THIS_DIR, "regression_v3_xgb.pkl")
META_PATH = os.path.join(THIS_DIR, "regression_v3_metadata.json")

TRAIN_END = pd.Timestamp("2026-03-31")
HOLDOUT_START = pd.Timestamp("2026-04-01")

FOLD_BOUNDARIES = [
    ("2021-01-01", "2021-12-31"),
    ("2022-01-01", "2022-12-31"),
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-12-31"),
    ("2025-01-01", "2025-12-31"),
]

# Magnitude buckets — keep aligned with feature_engineering.MAG_BUCKETS
MAG_BUCKETS = [0.0025, 0.0075, 0.015]   # |return| in fraction
MAG_LABELS = ["TINY (<0.25%)", "SMALL (0.25-0.75%)", "MEDIUM (0.75-1.5%)", "LARGE (>1.5%)"]


def make_xgb_reg(seed: int = 42) -> xgb.XGBRegressor:
    return xgb.XGBRegressor(
        objective="reg:squarederror",
        n_estimators=500, max_depth=4, learning_rate=0.04,
        subsample=0.8, colsample_bytree=0.7,
        min_child_weight=5, gamma=0.1,
        reg_lambda=1.5, reg_alpha=0.5,
        tree_method="hist", random_state=seed,
        n_jobs=-1,
    )


def magnitude_bucket(abs_pct: float) -> tuple[int, str]:
    if abs_pct < MAG_BUCKETS[0]:
        return 0, MAG_LABELS[0]
    if abs_pct < MAG_BUCKETS[1]:
        return 1, MAG_LABELS[1]
    if abs_pct < MAG_BUCKETS[2]:
        return 2, MAG_LABELS[2]
    return 3, MAG_LABELS[3]


def main():
    raw = pd.read_parquet(RAW_PATH)
    feats = build_features(raw)
    feat_cols, _, _ = split_features_targets(feats)

    X = feats[feat_cols].values.astype(np.float32)
    # Target: log-return scaled to percent (so model learns ~unit-scale values)
    y_logret_pct = (feats["y_logret"].values * 100).astype(np.float32)
    prev_close = feats["prev_close"].values.astype(np.float64)
    actual_close = feats["next_close"].values.astype(np.float64)
    dates = feats.index

    print(f"Features: {len(feat_cols)}, rows: {len(feats)}")
    print(f"Target std (logret %): {y_logret_pct.std():.3f}\n")

    fold_reports = []

    for i, (start, end) in enumerate(FOLD_BOUNDARIES, 1):
        ts_start, ts_end = pd.Timestamp(start), pd.Timestamp(end)
        train_mask = dates < ts_start
        test_mask = (dates >= ts_start) & (dates <= ts_end)
        if train_mask.sum() < 200 or test_mask.sum() < 30:
            continue

        m = make_xgb_reg()
        m.fit(X[train_mask], y_logret_pct[train_mask], verbose=False)
        y_pred_pct = m.predict(X[test_mask])

        # Derive predicted close
        pred_logret = y_pred_pct / 100.0
        pred_close = prev_close[test_mask] * np.exp(pred_logret)
        true_close = actual_close[test_mask]
        abs_err = np.abs(pred_close - true_close)
        abs_err_pct = abs_err / true_close * 100

        fold_reports.append({
            "fold": i,
            "test_window": f"{ts_start.date()}→{ts_end.date()}",
            "test_n": int(test_mask.sum()),
            "logret_mae_pct": round(float(np.mean(np.abs(y_pred_pct - y_logret_pct[test_mask]))), 4),
            "close_mae_pct": round(float(np.mean(abs_err_pct)), 4),
            "close_rmse_pct": round(float(np.sqrt(np.mean(abs_err_pct ** 2))), 4),
        })
        print(f"Fold {i}  {ts_start.date()}→{ts_end.date()}  "
              f"n={test_mask.sum()}  logret_MAE={fold_reports[-1]['logret_mae_pct']}  "
              f"close_MAE={fold_reports[-1]['close_mae_pct']}%  RMSE={fold_reports[-1]['close_rmse_pct']}%")

    avg_close_mae = float(np.mean([r["close_mae_pct"] for r in fold_reports]))
    avg_close_rmse = float(np.mean([r["close_rmse_pct"] for r in fold_reports]))
    print(f"\nWalk-forward avg close MAE: {avg_close_mae:.3f}%   RMSE: {avg_close_rmse:.3f}%")

    # ── Final model on full train, evaluate holdout ───────────────────────
    train_mask = dates <= TRAIN_END
    test_mask = dates >= HOLDOUT_START
    final_m = make_xgb_reg()
    final_m.fit(X[train_mask], y_logret_pct[train_mask], verbose=False)
    joblib.dump(final_m, REG_PATH)

    y_pred_pct = final_m.predict(X[test_mask])
    pred_close = prev_close[test_mask] * np.exp(y_pred_pct / 100.0)
    true_close = actual_close[test_mask]
    abs_err_pct = np.abs(pred_close - true_close) / true_close * 100

    print(f"\nHoldout close MAE: {abs_err_pct.mean():.3f}%   RMSE: {np.sqrt((abs_err_pct**2).mean()):.3f}%")
    holdout_df = pd.DataFrame({
        "date": [d.date().isoformat() for d in dates[test_mask]],
        "prev_close": np.round(prev_close[test_mask], 2),
        "predicted_close": np.round(pred_close, 2),
        "actual_close": np.round(true_close, 2),
        "abs_error_pct": np.round(abs_err_pct, 3),
    })
    print("\nHoldout per-day:")
    print(holdout_df.to_string(index=False))

    metadata = {
        "model_name": "overnight_nifty_regression_v3",
        "version": "v3",
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "n_features": len(feat_cols),
        "feature_columns": feat_cols,
        "target": "log_return_pct (scale by /100 to get log-return)",
        "logret_scale": 100.0,
        "magnitude_buckets_abs_pct": [b * 100 for b in MAG_BUCKETS],
        "magnitude_labels": MAG_LABELS,
        "walk_forward": {
            "avg_close_mae_pct": round(avg_close_mae, 3),
            "avg_close_rmse_pct": round(avg_close_rmse, 3),
            "folds": fold_reports,
        },
        "holdout": {
            "n": int(test_mask.sum()),
            "close_mae_pct": round(float(abs_err_pct.mean()), 3),
            "close_rmse_pct": round(float(np.sqrt((abs_err_pct ** 2).mean())), 3),
        },
    }
    with open(META_PATH, "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    md = ["# Overnight Nifty — Close Price Regression v3\n\n"]
    md.append(f"**Trained:** {metadata['trained_at']}  \n")
    md.append(f"**Architecture:** XGBoost regression on log-return (×100), 74 features\n\n")
    md.append("## Walk-forward (5-year out-of-sample)\n\n")
    md.append("| Fold | Test window | n | Log-return MAE (% units) | Close MAE % | Close RMSE % |\n")
    md.append("|---|---|---:|---:|---:|---:|\n")
    for r in fold_reports:
        md.append(f"| {r['fold']} | {r['test_window']} | {r['test_n']} | "
                   f"{r['logret_mae_pct']} | {r['close_mae_pct']}% | {r['close_rmse_pct']}% |\n")
    md.append(f"\n**Average:** close MAE **{avg_close_mae:.3f}%**, close RMSE **{avg_close_rmse:.3f}%**\n\n")
    md.append("## April 2026 holdout\n\n")
    md.append(f"Close MAE: **{abs_err_pct.mean():.3f}%**, RMSE: **{np.sqrt((abs_err_pct**2).mean()):.3f}%**\n\n")
    md.append(holdout_df.to_markdown(index=False)); md.append("\n")
    md_path = os.path.join(OUT_DIR, "v3_regression_report.md")
    with open(md_path, "w") as f:
        f.writelines(md)

    print(f"\nSaved:\n  model    → {REG_PATH}\n  metadata → {META_PATH}\n  report   → {md_path}")


if __name__ == "__main__":
    main()
