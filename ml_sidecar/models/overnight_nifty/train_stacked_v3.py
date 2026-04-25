"""
v3 — Stacked ensemble (XGBoost + LightGBM + Logistic meta-learner) with
isotonic probability calibration.

Pipeline:
  1. Walk-forward CV: 5 folds (2021-2025). For each fold, train base XGB and
     LGBM on data BEFORE the fold start. Predict probabilities on the fold.
  2. The base predictions across all 5 folds form an out-of-fold (OOF) matrix.
  3. Train a multinomial Logistic Regression *meta-learner* on the OOF matrix.
     This learns optimal weights for combining XGB and LGBM probabilities.
  4. Calibrate the meta-learner's probabilities with isotonic regression
     (per-class) so threshold filtering is statistically meaningful.
  5. Run conviction analysis on calibrated probabilities.
  6. Train final base models on all data ≤ 2026-03-31 + final meta + final
     calibrators. Save artifacts. Predict April 2026 holdout.

Output:
  • Per-fold report                 → backtest/overnight_lstm_holdout/v3_stacked_report.md
  • Conviction filter table         → same file
  • Final artifacts                 → overnight_nifty/stacked_v3_*.pkl
  • Per-day OOF + holdout preds     → overnight_nifty/data/v3_oof_preds.parquet
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

from feature_engineering import DIR_LABELS, build_features, split_features_targets

THIS_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(THIS_DIR, "data")
RAW_PATH = os.path.join(DATA_DIR, "overnight_raw.parquet")
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
OUT_DIR = os.path.join(REPO_ROOT, "backtest", "overnight_lstm_holdout")
os.makedirs(OUT_DIR, exist_ok=True)

XGB_PATH = os.path.join(THIS_DIR, "stacked_v3_xgb.pkl")
LGB_PATH = os.path.join(THIS_DIR, "stacked_v3_lgb.pkl")
META_PATH = os.path.join(THIS_DIR, "stacked_v3_meta.pkl")
CAL_PATH = os.path.join(THIS_DIR, "stacked_v3_calibrators.pkl")
META_JSON_PATH = os.path.join(THIS_DIR, "stacked_v3_metadata.json")
PREDS_PATH = os.path.join(DATA_DIR, "v3_oof_preds.parquet")

TRAIN_END = pd.Timestamp("2026-03-31")
HOLDOUT_START = pd.Timestamp("2026-04-01")

FOLD_BOUNDARIES = [
    ("2021-01-01", "2021-12-31"),
    ("2022-01-01", "2022-12-31"),
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-12-31"),
    ("2025-01-01", "2025-12-31"),
]


def make_xgb_clf(seed: int = 42) -> xgb.XGBClassifier:
    return xgb.XGBClassifier(
        objective="multi:softprob", num_class=3,
        n_estimators=500, max_depth=4, learning_rate=0.04,
        subsample=0.8, colsample_bytree=0.7,
        min_child_weight=5, gamma=0.1,
        reg_lambda=1.5, reg_alpha=0.5,
        tree_method="hist", random_state=seed,
        eval_metric="mlogloss", n_jobs=-1,
    )


def make_lgb_clf(seed: int = 42) -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(
        objective="multiclass", num_class=3,
        n_estimators=500, max_depth=-1, num_leaves=15,
        learning_rate=0.04,
        subsample=0.8, subsample_freq=1,
        colsample_bytree=0.7,
        min_child_samples=15,
        reg_lambda=1.5, reg_alpha=0.5,
        random_state=seed, n_jobs=-1, verbose=-1,
    )


def _bal_sample_weights(y: np.ndarray) -> np.ndarray:
    counts = np.bincount(y, minlength=3).astype(float)
    inv = 1.0 / np.maximum(counts, 1)
    inv = inv / inv.mean()
    return np.sqrt(inv)[y]


def main():
    raw = pd.read_parquet(RAW_PATH)
    feats = build_features(raw)
    feat_cols, _, _ = split_features_targets(feats)
    print(f"Features: {len(feat_cols)} | Rows: {len(feats)}")

    X = feats[feat_cols].values.astype(np.float32)
    y = feats["y_dir"].values.astype(np.int64)
    dates = feats.index

    # ── 1. Walk-forward base predictions ───────────────────────────────────
    fold_reports = []
    oof_xgb = np.full((len(feats), 3), np.nan, dtype=np.float64)
    oof_lgb = np.full((len(feats), 3), np.nan, dtype=np.float64)
    oof_fold = np.full(len(feats), -1, dtype=np.int64)

    for i, (start, end) in enumerate(FOLD_BOUNDARIES, 1):
        ts_start, ts_end = pd.Timestamp(start), pd.Timestamp(end)
        train_mask = dates < ts_start
        test_mask = (dates >= ts_start) & (dates <= ts_end)
        if train_mask.sum() < 200 or test_mask.sum() < 30:
            continue
        sw = _bal_sample_weights(y[train_mask])

        xgb_m = make_xgb_clf()
        xgb_m.fit(X[train_mask], y[train_mask], sample_weight=sw, verbose=False)
        lgb_m = make_lgb_clf()
        lgb_m.fit(X[train_mask], y[train_mask], sample_weight=sw)

        p_xgb = xgb_m.predict_proba(X[test_mask])
        p_lgb = lgb_m.predict_proba(X[test_mask])
        oof_xgb[test_mask] = p_xgb
        oof_lgb[test_mask] = p_lgb
        oof_fold[test_mask] = i

        # Per-base accuracy this fold
        y_pred_xgb = np.argmax(p_xgb, axis=1)
        y_pred_lgb = np.argmax(p_lgb, axis=1)
        nonflat_xgb = y_pred_xgb != 1
        nonflat_lgb = y_pred_lgb != 1
        do_xgb = float((y_pred_xgb[nonflat_xgb] == y[test_mask][nonflat_xgb]).mean()) if nonflat_xgb.sum() else float("nan")
        do_lgb = float((y_pred_lgb[nonflat_lgb] == y[test_mask][nonflat_lgb]).mean()) if nonflat_lgb.sum() else float("nan")

        fold_reports.append({
            "fold": i, "test_window": f"{ts_start.date()}→{ts_end.date()}", "test_n": int(test_mask.sum()),
            "xgb_acc": round(accuracy_score(y[test_mask], y_pred_xgb) * 100, 2),
            "xgb_dir_only": round(do_xgb * 100, 2) if not np.isnan(do_xgb) else None,
            "lgb_acc": round(accuracy_score(y[test_mask], y_pred_lgb) * 100, 2),
            "lgb_dir_only": round(do_lgb * 100, 2) if not np.isnan(do_lgb) else None,
        })
        print(f"Fold {i}  {ts_start.date()}→{ts_end.date()}  "
              f"XGB acc={fold_reports[-1]['xgb_acc']}% (dir-only {fold_reports[-1]['xgb_dir_only']}%)  "
              f"LGB acc={fold_reports[-1]['lgb_acc']}% (dir-only {fold_reports[-1]['lgb_dir_only']}%)")

    # ── 2. Train meta-learner on OOF predictions ──────────────────────────
    oof_mask = oof_fold > 0
    Z = np.hstack([oof_xgb[oof_mask], oof_lgb[oof_mask]])    # (N, 6)
    y_oof = y[oof_mask]
    print(f"\nMeta-learner training on {len(Z)} OOF predictions × 6 features")

    meta = LogisticRegression(
        multi_class="multinomial", solver="lbfgs", max_iter=2000,
        C=1.0, class_weight="balanced", random_state=42,
    )
    meta.fit(Z, y_oof)
    p_meta = meta.predict_proba(Z)
    y_pred_meta = np.argmax(p_meta, axis=1)
    nonflat_meta = y_pred_meta != 1
    meta_acc_3c = accuracy_score(y_oof, y_pred_meta)
    meta_dir_only = float((y_pred_meta[nonflat_meta] == y_oof[nonflat_meta]).mean()) if nonflat_meta.sum() else float("nan")
    print(f"Stacked OOF: 3-class={meta_acc_3c*100:.2f}%   directional-only={meta_dir_only*100:.2f}% (n={nonflat_meta.sum()})")

    # ── 3. Calibrate probabilities (per-class isotonic) ───────────────────
    # For each class k, fit isotonic regression: predicted_prob[k] → empirical_freq[k]
    calibrators = []
    p_cal = np.zeros_like(p_meta)
    for k in range(3):
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(p_meta[:, k], (y_oof == k).astype(float))
        calibrators.append(iso)
        p_cal[:, k] = iso.transform(p_meta[:, k])
    # Renormalise rows (post-calibration probs may not sum to 1)
    p_cal = p_cal / np.clip(p_cal.sum(axis=1, keepdims=True), 1e-9, None)
    y_pred_cal = np.argmax(p_cal, axis=1)
    nonflat_cal = y_pred_cal != 1
    cal_acc_3c = accuracy_score(y_oof, y_pred_cal)
    cal_dir_only = float((y_pred_cal[nonflat_cal] == y_oof[nonflat_cal]).mean()) if nonflat_cal.sum() else float("nan")
    print(f"Calibrated stacked: 3-class={cal_acc_3c*100:.2f}%   directional-only={cal_dir_only*100:.2f}% (n={nonflat_cal.sum()})")

    # ── 4. Conviction analysis on calibrated walk-forward preds ───────────
    p_top = p_cal.max(axis=1)
    print("\n=== Conviction filter on calibrated stacked walk-forward ===")
    conv_rows = []
    for thr in [0.0, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        keep = (p_top >= thr) & (y_pred_cal != 1)
        n = int(keep.sum())
        if n == 0:
            conv_rows.append({"threshold": thr, "trades": 0, "freq_pct": 0.0, "dir_acc_pct": None})
            continue
        acc = float((y_pred_cal[keep] == y_oof[keep]).mean())
        conv_rows.append({"threshold": thr, "trades": n,
                           "freq_pct": round(n / len(y_oof) * 100, 1),
                           "dir_acc_pct": round(acc * 100, 1)})
        print(f"  confidence>={thr:.2f}  trades={n:4d}  ({n/len(y_oof)*100:4.1f}%)  dir_acc={acc*100:.1f}%")

    # ── 5. Train final base models on ALL data ≤ TRAIN_END, predict holdout ─
    print("\n=== Final ensemble: train on ≤ 2026-03-31, predict April 2026 ===")
    train_mask = dates <= TRAIN_END
    test_mask = dates >= HOLDOUT_START
    sw = _bal_sample_weights(y[train_mask])
    final_xgb = make_xgb_clf()
    final_xgb.fit(X[train_mask], y[train_mask], sample_weight=sw, verbose=False)
    final_lgb = make_lgb_clf()
    final_lgb.fit(X[train_mask], y[train_mask], sample_weight=sw)

    p_xgb_h = final_xgb.predict_proba(X[test_mask])
    p_lgb_h = final_lgb.predict_proba(X[test_mask])
    Z_h = np.hstack([p_xgb_h, p_lgb_h])
    p_meta_h = meta.predict_proba(Z_h)
    p_cal_h = np.zeros_like(p_meta_h)
    for k in range(3):
        p_cal_h[:, k] = calibrators[k].transform(p_meta_h[:, k])
    p_cal_h = p_cal_h / np.clip(p_cal_h.sum(axis=1, keepdims=True), 1e-9, None)
    y_pred_h = np.argmax(p_cal_h, axis=1)
    y_te = y[test_mask]
    nonflat_h = y_pred_h != 1
    holdout_acc = accuracy_score(y_te, y_pred_h)
    holdout_dir_only = float((y_pred_h[nonflat_h] == y_te[nonflat_h]).mean()) if nonflat_h.sum() else float("nan")
    print(f"Holdout 3-class: {holdout_acc*100:.1f}%")
    print(f"Holdout dir-only: {holdout_dir_only*100:.1f}% (n={nonflat_h.sum()})")
    print(f"Predicted dist: {dict(zip(DIR_LABELS, np.bincount(y_pred_h, minlength=3).tolist()))}")

    # Conviction on holdout
    p_top_h = p_cal_h.max(axis=1)
    print("\nHoldout conviction:")
    for thr in [0.45, 0.50, 0.55, 0.60]:
        keep = (p_top_h >= thr) & (y_pred_h != 1)
        n = int(keep.sum())
        if n == 0:
            continue
        acc = float((y_pred_h[keep] == y_te[keep]).mean())
        print(f"  confidence>={thr:.2f}  trades={n}  dir_acc={acc*100:.1f}%")

    # ── 6. Save artifacts ─────────────────────────────────────────────────
    joblib.dump(final_xgb, XGB_PATH)
    joblib.dump(final_lgb, LGB_PATH)
    joblib.dump(meta, META_PATH)
    joblib.dump(calibrators, CAL_PATH)

    holdout_df = pd.DataFrame({
        "date": [d.date().isoformat() for d in dates[test_mask]],
        "actual_dir": [DIR_LABELS[c] for c in y_te],
        "pred_dir":   [DIR_LABELS[c] for c in y_pred_h],
        "p_down": p_cal_h[:, 0].round(3),
        "p_flat": p_cal_h[:, 1].round(3),
        "p_up":   p_cal_h[:, 2].round(3),
        "p_top":  p_top_h.round(3),
        "correct": y_pred_h == y_te,
    })

    # Save per-day OOF + holdout
    oof_df = pd.DataFrame({
        "date": dates[oof_mask],
        "fold": oof_fold[oof_mask],
        "actual_dir": [DIR_LABELS[c] for c in y_oof],
        "pred_dir":   [DIR_LABELS[c] for c in y_pred_cal],
        "p_down": p_cal[:, 0].round(4),
        "p_flat": p_cal[:, 1].round(4),
        "p_up":   p_cal[:, 2].round(4),
        "p_top":  p_top.round(4),
    })
    oof_df.to_parquet(PREDS_PATH)

    metadata = {
        "model_name": "overnight_nifty_stacked_v3",
        "version": "v3",
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "n_features": len(feat_cols),
        "feature_columns": feat_cols,
        "dir_labels": DIR_LABELS,
        "components": ["XGBoost", "LightGBM", "LogisticRegression-meta", "Isotonic-calibration"],
        "walk_forward_base": fold_reports,
        "walk_forward_stacked": {
            "uncalibrated": {"acc_3class": round(meta_acc_3c * 100, 2),
                              "dir_only": round(meta_dir_only * 100, 2) if not np.isnan(meta_dir_only) else None},
            "calibrated":   {"acc_3class": round(cal_acc_3c * 100, 2),
                              "dir_only": round(cal_dir_only * 100, 2) if not np.isnan(cal_dir_only) else None},
            "conviction": conv_rows,
        },
        "holdout": {
            "acc_3class_pct": round(holdout_acc * 100, 2),
            "dir_only_acc_pct": round(holdout_dir_only * 100, 2) if not np.isnan(holdout_dir_only) else None,
            "n": int(test_mask.sum()),
        },
    }
    with open(META_JSON_PATH, "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    # ── 7. Markdown report ────────────────────────────────────────────────
    md = ["# Overnight Nifty — Stacked Ensemble v3 Report\n\n"]
    md.append(f"**Trained at:** {metadata['trained_at']}  \n")
    md.append(f"**Architecture:** XGBoost + LightGBM → Logistic meta → isotonic calibration  \n")
    md.append(f"**Features:** {len(feat_cols)} (added 9 interaction/regime features in v3)\n\n")
    md.append("## Walk-forward base learners\n\n")
    md.append("| Fold | Test window | n | XGB acc | XGB dir-only | LGB acc | LGB dir-only |\n")
    md.append("|---|---|---:|---:|---:|---:|---:|\n")
    for r in fold_reports:
        md.append(f"| {r['fold']} | {r['test_window']} | {r['test_n']} | "
                   f"{r['xgb_acc']}% | {r['xgb_dir_only']}% | "
                   f"{r['lgb_acc']}% | {r['lgb_dir_only']}% |\n")
    md.append(f"\n## Stacked OOF (walk-forward across all 5 folds)\n\n")
    md.append(f"- Uncalibrated stacked: 3-class **{meta_acc_3c*100:.2f}%**, dir-only **{meta_dir_only*100:.2f}%** (n={nonflat_meta.sum()})\n")
    md.append(f"- Calibrated stacked:    3-class **{cal_acc_3c*100:.2f}%**, dir-only **{cal_dir_only*100:.2f}%** (n={nonflat_cal.sum()})\n\n")
    md.append("## Conviction filter on calibrated stacked OOF\n\n")
    md.append("| Threshold | Trades / 5y | Trade frequency | Dir-only accuracy |\n|---:|---:|---:|---:|\n")
    for r in conv_rows:
        md.append(f"| {r['threshold']:.2f} | {r['trades']} | {r['freq_pct']}% | "
                   f"{r['dir_acc_pct']}% |\n")
    md.append("\n## April 2026 holdout\n\n")
    md.append(f"- 3-class: **{holdout_acc*100:.1f}%**, dir-only: **{holdout_dir_only*100:.1f}%** (n={nonflat_h.sum()})\n\n")
    md.append(holdout_df.to_markdown(index=False)); md.append("\n")

    md_path = os.path.join(OUT_DIR, "v3_stacked_report.md")
    with open(md_path, "w") as f:
        f.writelines(md)

    print(f"\nArtifacts:")
    print(f"  XGB         → {XGB_PATH}")
    print(f"  LightGBM    → {LGB_PATH}")
    print(f"  Meta        → {META_PATH}")
    print(f"  Calibrators → {CAL_PATH}")
    print(f"  Metadata    → {META_JSON_PATH}")
    print(f"  Report      → {md_path}")
    print(f"  OOF preds   → {PREDS_PATH}")


if __name__ == "__main__":
    main()
