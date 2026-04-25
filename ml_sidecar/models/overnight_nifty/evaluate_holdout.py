"""
Evaluate the trained overnight LSTM on the holdout window (2026-04-01 → end).
Saves a per-day predicted-vs-actual table, accuracy stats, plots into:
    backtest/overnight_lstm_holdout/

Run after train_overnight_lstm.py finishes:
    python evaluate_holdout.py
"""
from __future__ import annotations

import io
import json
import os
import sys

import joblib
import numpy as np
import pandas as pd

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import tensorflow as tf

from feature_engineering import (
    DIR_LABELS, MAG_LABELS, build_features, split_features_targets,
)
from train_overnight_lstm import SumOverTime  # noqa: F401 — registers custom layer

THIS_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(THIS_DIR, "data")
RAW_PATH = os.path.join(DATA_DIR, "overnight_raw.parquet")

MODEL_PATH = os.path.join(THIS_DIR, "overnight_lstm.keras")
SCALER_PATH = os.path.join(THIS_DIR, "overnight_scaler.pkl")
META_PATH = os.path.join(THIS_DIR, "overnight_metadata.json")

REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
OUT_DIR = os.path.join(REPO_ROOT, "backtest", "overnight_lstm_holdout")
PLOTS_DIR = os.path.join(OUT_DIR, "plots")
os.makedirs(PLOTS_DIR, exist_ok=True)


def main():
    with open(META_PATH) as f:
        meta = json.load(f)
    seq_len = meta["seq_len"]
    feat_cols = meta["feature_columns"]
    logret_scale = meta.get("logret_scale", 1.0)
    holdout_start = pd.Timestamp(meta["holdout_start"])

    print(f"Model meta: seq_len={seq_len}, n_features={len(feat_cols)}, "
          f"logret_scale={logret_scale}")
    print(f"Holdout window: {holdout_start.date()} → end")

    raw = pd.read_parquet(RAW_PATH)
    feats = build_features(raw)
    feat_cols2, X_df, y_df = split_features_targets(feats)
    if feat_cols2 != feat_cols:
        missing = set(feat_cols) - set(feat_cols2)
        extra = set(feat_cols2) - set(feat_cols)
        raise SystemExit(f"Feature column mismatch.\n  missing in current: {missing}\n  extra in current: {extra}")

    scaler = joblib.load(SCALER_PATH)
    model = tf.keras.models.load_model(MODEL_PATH)

    X_all = scaler.transform(X_df.values.astype(np.float32))

    # For each holdout date, build a sequence ending on that date
    holdout_idx = np.where(feats.index >= holdout_start)[0]
    rows = []
    for idx in holdout_idx:
        if idx < seq_len - 1:
            continue   # not enough lookback
        seq = X_all[idx - seq_len + 1 : idx + 1][np.newaxis, :, :]
        reg_pred, dir_probs, mag_probs = model.predict(seq, verbose=0)
        reg_logret = float(reg_pred[0, 0]) / logret_scale
        dir_idx = int(np.argmax(dir_probs[0]))
        mag_idx = int(np.argmax(mag_probs[0]))
        prev_close = float(feats["prev_close"].iloc[idx])
        actual_close = float(feats["next_close"].iloc[idx])
        predicted_close = prev_close * float(np.exp(reg_logret))
        actual_logret = float(feats["y_logret"].iloc[idx])
        actual_dir = int(feats["y_dir"].iloc[idx])
        actual_mag = int(feats["y_mag"].iloc[idx])
        rows.append({
            "date": feats.index[idx].date().isoformat(),
            "prev_close": round(prev_close, 2),
            "actual_close": round(actual_close, 2),
            "predicted_close": round(predicted_close, 2),
            "predicted_logret_pct": round(reg_logret * 100, 3),
            "actual_logret_pct": round(actual_logret * 100, 3),
            "predicted_direction": DIR_LABELS[dir_idx],
            "actual_direction": DIR_LABELS[actual_dir],
            "direction_correct": dir_idx == actual_dir,
            "predicted_magnitude": MAG_LABELS[mag_idx],
            "actual_magnitude": MAG_LABELS[actual_mag],
            "magnitude_correct": mag_idx == actual_mag,
            "dir_confidence_pct": round(float(np.max(dir_probs[0])) * 100, 1),
            "mag_confidence_pct": round(float(np.max(mag_probs[0])) * 100, 1),
            "abs_error_pct": round(abs(actual_close - predicted_close) / actual_close * 100, 3),
        })

    if not rows:
        raise SystemExit(f"No holdout rows after seq_len cutoff. Need ≥{seq_len} rows before holdout_start.")

    df = pd.DataFrame(rows)
    csv_path = os.path.join(OUT_DIR, "predicted_vs_actual.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nSaved per-day table → {csv_path}\n")
    print(df.to_string(index=False))

    # ── Stats ────────────────────────────────────────────────────────────
    abs_err_pct = df["abs_error_pct"].values
    mae_pct = float(np.mean(abs_err_pct))
    rmse_pct = float(np.sqrt(np.mean(abs_err_pct ** 2)))
    dir_acc = float(df["direction_correct"].mean())
    mag_acc = float(df["magnitude_correct"].mean())

    # Direction-only accuracy ignoring FLAT (treat FLAT pred as "no signal")
    non_flat = df[df["predicted_direction"] != "FLAT"]
    if len(non_flat) > 0:
        directional_only_acc = float((non_flat["predicted_direction"] == non_flat["actual_direction"]).mean())
        directional_only_n = len(non_flat)
    else:
        directional_only_acc = float("nan")
        directional_only_n = 0

    # Confusion matrix
    confusion = pd.crosstab(df["actual_direction"], df["predicted_direction"], dropna=False)

    stats = {
        "holdout_n": int(len(df)),
        "holdout_dates": [df["date"].iloc[0], df["date"].iloc[-1]],
        "close_prediction": {
            "mae_pct": round(mae_pct, 3),
            "rmse_pct": round(rmse_pct, 3),
        },
        "direction": {
            "accuracy_3class": round(dir_acc * 100, 1),
            "directional_only_accuracy_pct": round(directional_only_acc * 100, 1) if not np.isnan(directional_only_acc) else None,
            "directional_only_n": directional_only_n,
        },
        "magnitude": {"accuracy_4class_pct": round(mag_acc * 100, 1)},
    }
    stats_path = os.path.join(OUT_DIR, "stats.json")
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    # ── Plots ─────────────────────────────────────────────────────────────
    plt.figure(figsize=(11, 5))
    dates = pd.to_datetime(df["date"])
    plt.plot(dates, df["actual_close"], "o-", label="Actual close", linewidth=2)
    plt.plot(dates, df["predicted_close"], "s--", label="Predicted close", linewidth=2)
    plt.title("Overnight LSTM — Predicted vs Actual Nifty Close (Holdout)")
    plt.ylabel("Nifty 50")
    plt.legend(); plt.grid(alpha=0.3); plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "predicted_vs_actual.png"), dpi=130)
    plt.close()

    plt.figure(figsize=(11, 4))
    err = df["predicted_close"] - df["actual_close"]
    plt.bar(dates, err, color=["green" if e >= 0 else "red" for e in err])
    plt.axhline(0, color="black", linewidth=0.5)
    plt.title("Prediction error (predicted − actual), Nifty points")
    plt.ylabel("Error (₹)"); plt.grid(alpha=0.3); plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, "errors.png"), dpi=130)
    plt.close()

    # ── Markdown report ──────────────────────────────────────────────────
    md_path = os.path.join(OUT_DIR, "holdout_report.md")
    with open(md_path, "w") as f:
        f.write(f"# Overnight Nifty LSTM — Holdout Report\n\n")
        f.write(f"**Model:** {meta.get('model_name', 'overnight_nifty_lstm')} ({meta.get('version', 'v1')})\n  \n")
        f.write(f"**Trained at:** {meta.get('trained_at', 'unknown')}\n  \n")
        f.write(f"**Train window:** {meta.get('train_start')} → {meta.get('train_end')}  \n")
        f.write(f"**Holdout window:** {df['date'].iloc[0]} → {df['date'].iloc[-1]}  ({len(df)} trading days)\n\n")
        f.write("## Headline numbers\n\n")
        f.write(f"| Metric | Value |\n|---|---|\n")
        f.write(f"| Close MAE (% of price) | {mae_pct:.3f}% |\n")
        f.write(f"| Close RMSE (% of price) | {rmse_pct:.3f}% |\n")
        f.write(f"| Direction accuracy (3-class) | {dir_acc*100:.1f}% (random = 33.3%) |\n")
        if not np.isnan(directional_only_acc):
            f.write(f"| Directional accuracy (UP/DOWN only, ignoring FLAT predictions) | {directional_only_acc*100:.1f}% on n={directional_only_n} |\n")
        f.write(f"| Magnitude bucket accuracy (4-class) | {mag_acc*100:.1f}% (random = 25%) |\n\n")
        f.write("## Direction confusion matrix\n\n")
        f.write("Rows = actual, Cols = predicted\n\n```\n")
        f.write(confusion.to_string())
        f.write("\n```\n\n")
        f.write("## Per-day predictions\n\n")
        cols_show = ["date", "actual_close", "predicted_close", "abs_error_pct",
                     "predicted_direction", "actual_direction", "direction_correct",
                     "predicted_magnitude", "dir_confidence_pct"]
        f.write(df[cols_show].to_markdown(index=False))
        f.write("\n\n## Plots\n\n")
        f.write("- ![Predicted vs actual](plots/predicted_vs_actual.png)\n")
        f.write("- ![Errors](plots/errors.png)\n")

    print("\n— Holdout summary —")
    print(json.dumps(stats, indent=2))
    print(f"\nReport saved: {md_path}")
    print(f"Stats:       {stats_path}")
    print(f"Plots:       {PLOTS_DIR}/")


if __name__ == "__main__":
    main()
