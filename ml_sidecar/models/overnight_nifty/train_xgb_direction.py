"""
Walk-forward XGBoost direction baseline for the overnight Nifty model.

Strategy:
  • Tabular features (no sequences) — XGBoost handles small N better than LSTM
  • Walk-forward CV: 5 expanding folds over 2018-2026, each predicts ~1 year ahead
  • Final model: trained on EVERYTHING through 2026-03-31, evaluated on 2026-04 holdout

This is the truth-test: if XGB can't show >50% directional accuracy on
walk-forward, the LSTM won't either, and we know the features are the bottleneck.

Output:
  • Walk-forward fold-by-fold report  → backtest/overnight_lstm_holdout/xgb_walkforward.md
  • Final model artifact              → overnight_nifty/xgb_direction.pkl
  • Holdout report (final fold)       → backtest/overnight_lstm_holdout/xgb_holdout_report.md
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

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import xgboost as xgb
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from feature_engineering import (
    DIR_LABELS, build_features, split_features_targets,
)

THIS_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(THIS_DIR, "data")
RAW_PATH = os.path.join(DATA_DIR, "overnight_raw.parquet")

REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
OUT_DIR = os.path.join(REPO_ROOT, "backtest", "overnight_lstm_holdout")
os.makedirs(OUT_DIR, exist_ok=True)

MODEL_PATH = os.path.join(THIS_DIR, "xgb_direction.pkl")
META_PATH = os.path.join(THIS_DIR, "xgb_metadata.json")

TRAIN_END = pd.Timestamp("2026-03-31")
HOLDOUT_START = pd.Timestamp("2026-04-01")

# Walk-forward fold boundaries — each test window is one calendar year
FOLD_BOUNDARIES = [
    ("2021-01-01", "2021-12-31"),
    ("2022-01-01", "2022-12-31"),
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-12-31"),
    ("2025-01-01", "2025-12-31"),
]


def make_xgb(n_classes: int = 3, seed: int = 42) -> xgb.XGBClassifier:
    return xgb.XGBClassifier(
        objective="multi:softprob",
        num_class=n_classes,
        n_estimators=400,
        max_depth=4,
        learning_rate=0.04,
        subsample=0.8,
        colsample_bytree=0.7,
        min_child_weight=5,
        gamma=0.1,
        reg_lambda=1.5,
        reg_alpha=0.5,
        tree_method="hist",
        random_state=seed,
        eval_metric="mlogloss",
        n_jobs=-1,
    )


def _bal_sample_weights(y: np.ndarray) -> np.ndarray:
    counts = np.bincount(y, minlength=3).astype(float)
    inv = 1.0 / np.maximum(counts, 1)
    inv = inv / inv.mean()           # normalise so mean weight ≈ 1
    return np.sqrt(inv)[y]           # mild balancing


def walk_forward(feats: pd.DataFrame, feat_cols: list[str]) -> tuple[list[dict], pd.DataFrame]:
    """Returns per-fold metrics and a full predicted-vs-actual DataFrame for all folds."""
    X = feats[feat_cols].values.astype(np.float32)
    y = feats["y_dir"].values.astype(np.int64)
    dates = feats.index

    fold_reports: list[dict] = []
    all_preds: list[pd.DataFrame] = []

    for i, (start, end) in enumerate(FOLD_BOUNDARIES, 1):
        ts_start, ts_end = pd.Timestamp(start), pd.Timestamp(end)
        train_mask = dates < ts_start
        test_mask = (dates >= ts_start) & (dates <= ts_end)
        if train_mask.sum() < 200 or test_mask.sum() < 30:
            print(f"Fold {i}: skipping (train={train_mask.sum()}, test={test_mask.sum()})")
            continue

        X_tr, y_tr = X[train_mask], y[train_mask]
        X_te, y_te = X[test_mask], y[test_mask]
        sw = _bal_sample_weights(y_tr)

        model = make_xgb()
        model.fit(X_tr, y_tr, sample_weight=sw, verbose=False)

        y_pred = model.predict(X_te)
        y_proba = model.predict_proba(X_te)
        acc = accuracy_score(y_te, y_pred)
        # Directional-only accuracy on UP/DOWN predictions (skip FLAT)
        nonflat = y_pred != 1
        dir_only = float((y_pred[nonflat] == y_te[nonflat]).mean()) if nonflat.sum() > 0 else float("nan")
        fold_reports.append({
            "fold": i,
            "train_n": int(train_mask.sum()),
            "train_window": f"{dates[train_mask].min().date()} → {dates[train_mask].max().date()}",
            "test_window": f"{ts_start.date()} → {ts_end.date()}",
            "test_n": int(test_mask.sum()),
            "accuracy_3class": round(acc * 100, 2),
            "directional_only_acc": round(dir_only * 100, 2) if not np.isnan(dir_only) else None,
            "directional_only_n": int(nonflat.sum()),
            "predicted_dist": dict(zip(DIR_LABELS, np.bincount(y_pred, minlength=3).tolist())),
            "actual_dist": dict(zip(DIR_LABELS, np.bincount(y_te, minlength=3).tolist())),
        })
        print(f"Fold {i}  train_n={train_mask.sum()}  test={ts_start.date()}→{ts_end.date()}  "
              f"acc={acc*100:.1f}%  dir_only={dir_only*100 if not np.isnan(dir_only) else float('nan'):.1f}% "
              f"(n_nonflat={nonflat.sum()})")

        all_preds.append(pd.DataFrame({
            "date": dates[test_mask],
            "fold": i,
            "actual_dir": [DIR_LABELS[c] for c in y_te],
            "pred_dir":   [DIR_LABELS[c] for c in y_pred],
            "p_down": y_proba[:, 0],
            "p_flat": y_proba[:, 1],
            "p_up":   y_proba[:, 2],
        }))

    pred_df = pd.concat(all_preds, ignore_index=True) if all_preds else pd.DataFrame()
    return fold_reports, pred_df


def fit_final_and_holdout(feats: pd.DataFrame, feat_cols: list[str]) -> dict:
    """Train on all data ≤ TRAIN_END, evaluate on holdout."""
    X = feats[feat_cols].values.astype(np.float32)
    y = feats["y_dir"].values.astype(np.int64)
    dates = feats.index

    train_mask = dates <= TRAIN_END
    test_mask = dates >= HOLDOUT_START
    print(f"\nFinal model: train_n={train_mask.sum()}, holdout_n={test_mask.sum()}")

    sw = _bal_sample_weights(y[train_mask])
    model = make_xgb()
    model.fit(X[train_mask], y[train_mask], sample_weight=sw, verbose=False)
    joblib.dump(model, MODEL_PATH)

    y_te = y[test_mask]
    y_pred = model.predict(X[test_mask])
    y_proba = model.predict_proba(X[test_mask])
    acc = accuracy_score(y_te, y_pred)
    nonflat = y_pred != 1
    dir_only = float((y_pred[nonflat] == y_te[nonflat]).mean()) if nonflat.sum() > 0 else float("nan")

    holdout_df = pd.DataFrame({
        "date": [d.date().isoformat() for d in dates[test_mask]],
        "actual_dir": [DIR_LABELS[c] for c in y_te],
        "pred_dir":   [DIR_LABELS[c] for c in y_pred],
        "p_down": y_proba[:, 0].round(3),
        "p_flat": y_proba[:, 1].round(3),
        "p_up":   y_proba[:, 2].round(3),
        "correct": y_pred == y_te,
    })

    # Feature importance (top 15)
    imp = pd.DataFrame({
        "feature": feat_cols,
        "importance": model.feature_importances_,
    }).sort_values("importance", ascending=False)

    return {
        "accuracy_3class_pct": round(acc * 100, 2),
        "directional_only_acc_pct": round(dir_only * 100, 2) if not np.isnan(dir_only) else None,
        "directional_only_n": int(nonflat.sum()),
        "holdout_n": int(test_mask.sum()),
        "confusion": pd.crosstab(holdout_df["actual_dir"], holdout_df["pred_dir"]).to_dict(),
        "predicted_dist": dict(zip(DIR_LABELS, np.bincount(y_pred, minlength=3).tolist())),
        "holdout_table": holdout_df,
        "top_features": imp.head(15).to_dict("records"),
    }


def main():
    raw = pd.read_parquet(RAW_PATH)
    feats = build_features(raw)
    feat_cols, _, _ = split_features_targets(feats)
    print(f"Features: {len(feat_cols)}, rows: {len(feats)}")

    print("\n=== Walk-forward CV ===")
    fold_reports, all_preds = walk_forward(feats, feat_cols)

    # Aggregate
    if fold_reports:
        wf_avg_3c = float(np.mean([r["accuracy_3class"] for r in fold_reports]))
        dir_only_vals = [r["directional_only_acc"] for r in fold_reports if r["directional_only_acc"] is not None]
        wf_avg_dir = float(np.mean(dir_only_vals)) if dir_only_vals else float("nan")
        print(f"\nWalk-forward averages: 3-class={wf_avg_3c:.2f}%   directional-only={wf_avg_dir:.2f}%")
    else:
        wf_avg_3c = wf_avg_dir = float("nan")

    print("\n=== Final model on holdout ===")
    holdout = fit_final_and_holdout(feats, feat_cols)
    print(f"Holdout 3-class acc: {holdout['accuracy_3class_pct']}%")
    print(f"Holdout directional-only acc: {holdout['directional_only_acc_pct']}% on n={holdout['directional_only_n']}")
    print(f"Predicted dist: {holdout['predicted_dist']}")
    print("\nTop 15 features:")
    for f in holdout["top_features"]:
        print(f"  {f['feature']:25s} {f['importance']:.4f}")

    # ── Save metadata + report ────────────────────────────────────────────
    meta = {
        "model_name": "overnight_nifty_xgb_direction",
        "version": "v2",
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "n_features": len(feat_cols),
        "feature_columns": feat_cols,
        "dir_labels": DIR_LABELS,
        "train_end": str(TRAIN_END.date()),
        "holdout_start": str(HOLDOUT_START.date()),
        "walk_forward": {
            "avg_3class_acc_pct": round(wf_avg_3c, 2) if not np.isnan(wf_avg_3c) else None,
            "avg_directional_only_acc_pct": round(wf_avg_dir, 2) if not np.isnan(wf_avg_dir) else None,
            "folds": fold_reports,
        },
        "holdout": {
            "accuracy_3class_pct": holdout["accuracy_3class_pct"],
            "directional_only_acc_pct": holdout["directional_only_acc_pct"],
            "directional_only_n": holdout["directional_only_n"],
            "predicted_dist": holdout["predicted_dist"],
            "confusion": holdout["confusion"],
            "top_features": holdout["top_features"],
        },
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2, default=str)

    md = []
    md.append("# Overnight Nifty XGBoost — Direction-only baseline (v2)\n")
    md.append(f"**Trained at:** {meta['trained_at']}  \n")
    md.append(f"**Features:** {len(feat_cols)} (after dropping Dow, adding HSI/KOSPI/Copper/MOVE/FTSE/DAX)  \n")
    md.append(f"**Train through:** {TRAIN_END.date()}  |  **Holdout from:** {HOLDOUT_START.date()}\n")
    md.append("\n## Walk-forward summary\n")
    md.append(f"- Average 3-class accuracy: **{wf_avg_3c:.2f}%**  (random=33.3%, all-majority≈38%)\n")
    md.append(f"- Average directional-only accuracy (UP/DOWN preds, ignoring FLAT): **{wf_avg_dir:.2f}%**  (coin-flip=50%)\n\n")
    md.append("| Fold | Train window | Test window | Test n | 3-class acc | Dir-only acc (n) | Predicted dist |\n")
    md.append("|---|---|---|---:|---:|---|---|\n")
    for r in fold_reports:
        md.append(f"| {r['fold']} | {r['train_window']} | {r['test_window']} | {r['test_n']} | "
                  f"{r['accuracy_3class']}% | {r['directional_only_acc']}% (n={r['directional_only_n']}) | "
                  f"{r['predicted_dist']} |\n")
    md.append("\n## Final-model holdout (April 2026)\n")
    md.append(f"- 3-class accuracy: **{holdout['accuracy_3class_pct']}%**\n")
    md.append(f"- Directional-only accuracy: **{holdout['directional_only_acc_pct']}%** on n={holdout['directional_only_n']}\n")
    md.append(f"- Predicted distribution: {holdout['predicted_dist']}\n\n")
    md.append("### Per-day predictions\n\n")
    md.append(holdout["holdout_table"].to_markdown(index=False))
    md.append("\n\n### Top features by importance\n\n")
    md.append("| Feature | Importance |\n|---|---:|\n")
    for f in holdout["top_features"]:
        md.append(f"| {f['feature']} | {f['importance']:.4f} |\n")

    md_path = os.path.join(OUT_DIR, "xgb_walkforward_report.md")
    with open(md_path, "w") as f:
        f.writelines(md)
    print(f"\nSaved:\n  model    → {MODEL_PATH}\n  metadata → {META_PATH}\n  report   → {md_path}")


if __name__ == "__main__":
    main()
