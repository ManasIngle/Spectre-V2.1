"""
Direction-only LSTM with walk-forward CV — v2 iteration.

Simplified architecture: single classification head (DOWN/FLAT/UP). Same 65
features as XGBoost. Walk-forward fold boundaries match XGBoost so results
are directly comparable.

Output:
  • per-fold metrics → backtest/overnight_lstm_holdout/lstm_walkforward_report.md
  • final model      → overnight_nifty/lstm_direction.keras
  • per-day preds    → overnight_nifty/data/lstm_walkforward_preds.parquet
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

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import tensorflow as tf
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_class_weight

from feature_engineering import DIR_LABELS, build_features, split_features_targets
from train_overnight_lstm import SumOverTime  # noqa: F401 — registers custom layer

THIS_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(THIS_DIR, "data")
RAW_PATH = os.path.join(DATA_DIR, "overnight_raw.parquet")
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
OUT_DIR = os.path.join(REPO_ROOT, "backtest", "overnight_lstm_holdout")

MODEL_PATH = os.path.join(THIS_DIR, "lstm_direction.keras")
SCALER_PATH = os.path.join(THIS_DIR, "lstm_direction_scaler.pkl")
META_PATH = os.path.join(THIS_DIR, "lstm_direction_metadata.json")
PREDS_PATH = os.path.join(DATA_DIR, "lstm_walkforward_preds.parquet")

TRAIN_END = pd.Timestamp("2026-03-31")
HOLDOUT_START = pd.Timestamp("2026-04-01")

FOLD_BOUNDARIES = [
    ("2021-01-01", "2021-12-31"),
    ("2022-01-01", "2022-12-31"),
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-12-31"),
    ("2025-01-01", "2025-12-31"),
]

SEQ_LEN = 60
EPOCHS = 50
BATCH = 64


def build_model(seq_len: int, n_features: int) -> tf.keras.Model:
    L2 = tf.keras.regularizers.l2(1e-4)
    inp = tf.keras.layers.Input(shape=(seq_len, n_features), name="seq")
    x = tf.keras.layers.LSTM(64, return_sequences=True, dropout=0.35,
                              kernel_regularizer=L2, recurrent_regularizer=L2)(inp)
    x = tf.keras.layers.LayerNormalization()(x)
    x = tf.keras.layers.LSTM(32, return_sequences=True, dropout=0.35,
                              kernel_regularizer=L2, recurrent_regularizer=L2)(x)
    x = tf.keras.layers.LayerNormalization()(x)
    attn_scores = tf.keras.layers.Dense(1, activation="tanh", kernel_regularizer=L2)(x)
    attn_weights = tf.keras.layers.Softmax(axis=1, name="attn_weights")(attn_scores)
    context = tf.keras.layers.Multiply()([x, attn_weights])
    pooled = SumOverTime(name="attn_pool")(context)
    h = tf.keras.layers.Dense(32, activation="relu", kernel_regularizer=L2)(pooled)
    h = tf.keras.layers.Dropout(0.4)(h)
    out = tf.keras.layers.Dense(3, activation="softmax", name="dir", kernel_regularizer=L2)(h)
    return tf.keras.Model(inp, out)


def make_sequences_indexed(X: np.ndarray, y: np.ndarray, indices: np.ndarray, seq_len: int):
    """Build sequences ending at each index in `indices`. Requires idx >= seq_len-1."""
    Xs, ys, keep_idx = [], [], []
    for t in indices:
        if t < seq_len - 1:
            continue
        Xs.append(X[t - seq_len + 1 : t + 1])
        ys.append(y[t])
        keep_idx.append(t)
    return (np.asarray(Xs, dtype=np.float32),
            np.asarray(ys, dtype=np.int64),
            np.asarray(keep_idx, dtype=np.int64))


def train_fold(X_train_seq: np.ndarray, y_train_seq: np.ndarray,
               X_val_seq: np.ndarray | None, y_val_seq: np.ndarray | None,
               seed: int = 42) -> tf.keras.Model:
    np.random.seed(seed); tf.random.set_seed(seed)

    cls_w = compute_class_weight("balanced", classes=np.array([0, 1, 2]), y=y_train_seq)
    cls_w = np.sqrt(cls_w)    # mild
    sw = np.array([cls_w[c] for c in y_train_seq], dtype=np.float32)

    model = build_model(SEQ_LEN, X_train_seq.shape[2])
    model.compile(
        optimizer=tf.keras.optimizers.Adam(5e-4, clipnorm=1.0),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(),
        metrics=[tf.keras.metrics.SparseCategoricalAccuracy(name="acc")],
    )
    cbs = [
        tf.keras.callbacks.EarlyStopping(monitor="val_acc" if X_val_seq is not None else "loss",
                                          mode="max" if X_val_seq is not None else "min",
                                          patience=8, restore_best_weights=True, verbose=0),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss" if X_val_seq is not None else "loss",
                                              factor=0.5, patience=3, min_lr=1e-6, verbose=0),
    ]
    vd = (X_val_seq, y_val_seq) if X_val_seq is not None else None
    model.fit(X_train_seq, y_train_seq, sample_weight=sw,
              validation_data=vd, epochs=EPOCHS, batch_size=BATCH,
              callbacks=cbs, verbose=0)
    return model


def main():
    raw = pd.read_parquet(RAW_PATH)
    feats = build_features(raw)
    feat_cols, _, _ = split_features_targets(feats)
    print(f"Features: {len(feat_cols)}, rows: {len(feats)}")

    X = feats[feat_cols].values.astype(np.float32)
    y = feats["y_dir"].values.astype(np.int64)
    dates = feats.index
    idx = np.arange(len(feats))

    fold_reports, all_preds = [], []

    for i, (start, end) in enumerate(FOLD_BOUNDARIES, 1):
        ts_start, ts_end = pd.Timestamp(start), pd.Timestamp(end)
        train_idx = idx[dates < ts_start]
        test_idx = idx[(dates >= ts_start) & (dates <= ts_end)]
        if len(train_idx) < 200 or len(test_idx) < 30:
            print(f"Fold {i}: skipping")
            continue

        # Scale on train raw rows only (no sequence info)
        scaler = StandardScaler().fit(X[train_idx])
        X_scaled = scaler.transform(X)

        # Build sequences
        X_tr, y_tr, _ = make_sequences_indexed(X_scaled, y, train_idx, SEQ_LEN)
        X_te, y_te, te_kept = make_sequences_indexed(X_scaled, y, test_idx, SEQ_LEN)

        # Inner val: last 10% of training sequences
        n_val = max(30, int(len(X_tr) * 0.10))
        X_tr_tr, X_tr_val = X_tr[:-n_val], X_tr[-n_val:]
        y_tr_tr, y_tr_val = y_tr[:-n_val], y_tr[-n_val:]

        print(f"Fold {i}: train_seq={len(X_tr_tr)}, val_seq={len(X_tr_val)}, test_seq={len(X_te)}")
        model = train_fold(X_tr_tr, y_tr_tr, X_tr_val, y_tr_val)

        y_proba = model.predict(X_te, verbose=0)
        y_pred = np.argmax(y_proba, axis=1)
        acc = accuracy_score(y_te, y_pred)
        nonflat = y_pred != 1
        dir_only = float((y_pred[nonflat] == y_te[nonflat]).mean()) if nonflat.sum() > 0 else float("nan")
        fold_reports.append({
            "fold": i,
            "train_n": int(len(X_tr_tr)),
            "test_window": f"{ts_start.date()} → {ts_end.date()}",
            "test_n": int(len(X_te)),
            "accuracy_3class": round(acc * 100, 2),
            "directional_only_acc": round(dir_only * 100, 2) if not np.isnan(dir_only) else None,
            "directional_only_n": int(nonflat.sum()),
            "predicted_dist": dict(zip(DIR_LABELS, np.bincount(y_pred, minlength=3).tolist())),
        })
        print(f"  acc={acc*100:.1f}%  dir_only={dir_only*100 if not np.isnan(dir_only) else float('nan'):.1f}% (n={nonflat.sum()})")

        all_preds.append(pd.DataFrame({
            "date": dates[te_kept],
            "fold": i,
            "actual_dir": [DIR_LABELS[c] for c in y_te],
            "pred_dir":   [DIR_LABELS[c] for c in y_pred],
            "p_down": y_proba[:, 0],
            "p_flat": y_proba[:, 1],
            "p_up":   y_proba[:, 2],
        }))

    # Aggregate
    wf_avg_3c = float(np.mean([r["accuracy_3class"] for r in fold_reports])) if fold_reports else float("nan")
    dir_vals = [r["directional_only_acc"] for r in fold_reports if r["directional_only_acc"] is not None]
    wf_avg_dir = float(np.mean(dir_vals)) if dir_vals else float("nan")
    print(f"\nWalk-forward averages: 3-class={wf_avg_3c:.2f}%   directional-only={wf_avg_dir:.2f}%")

    # Final model: train on everything ≤ TRAIN_END, predict holdout
    print("\n=== Final model on holdout ===")
    train_idx = idx[dates <= TRAIN_END]
    test_idx = idx[dates >= HOLDOUT_START]
    scaler = StandardScaler().fit(X[train_idx])
    X_scaled = scaler.transform(X)
    X_tr, y_tr, _ = make_sequences_indexed(X_scaled, y, train_idx, SEQ_LEN)
    X_te, y_te, te_kept = make_sequences_indexed(X_scaled, y, test_idx, SEQ_LEN)
    n_val = max(30, int(len(X_tr) * 0.08))
    model = train_fold(X_tr[:-n_val], y_tr[:-n_val], X_tr[-n_val:], y_tr[-n_val:])
    model.save(MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)

    y_proba = model.predict(X_te, verbose=0)
    y_pred = np.argmax(y_proba, axis=1)
    holdout_acc = accuracy_score(y_te, y_pred)
    nonflat = y_pred != 1
    dir_only = float((y_pred[nonflat] == y_te[nonflat]).mean()) if nonflat.sum() > 0 else float("nan")
    print(f"Holdout 3-class acc: {holdout_acc*100:.1f}%")
    print(f"Holdout dir-only acc: {dir_only*100 if not np.isnan(dir_only) else float('nan'):.1f}% (n={nonflat.sum()})")
    print(f"Predicted dist: {dict(zip(DIR_LABELS, np.bincount(y_pred, minlength=3).tolist()))}")

    holdout_df = pd.DataFrame({
        "date": [d.date().isoformat() for d in dates[te_kept]],
        "actual_dir": [DIR_LABELS[c] for c in y_te],
        "pred_dir":   [DIR_LABELS[c] for c in y_pred],
        "p_down": y_proba[:, 0].round(3),
        "p_flat": y_proba[:, 1].round(3),
        "p_up":   y_proba[:, 2].round(3),
        "correct": y_pred == y_te,
    })
    all_preds.append(pd.DataFrame({
        "date": dates[te_kept], "fold": 99, "actual_dir": [DIR_LABELS[c] for c in y_te],
        "pred_dir": [DIR_LABELS[c] for c in y_pred],
        "p_down": y_proba[:, 0], "p_flat": y_proba[:, 1], "p_up": y_proba[:, 2],
    }))
    preds = pd.concat(all_preds, ignore_index=True)
    preds.to_parquet(PREDS_PATH)

    meta = {
        "model_name": "overnight_nifty_lstm_direction",
        "version": "v2",
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "seq_len": SEQ_LEN,
        "n_features": len(feat_cols),
        "feature_columns": feat_cols,
        "dir_labels": DIR_LABELS,
        "walk_forward": {
            "avg_3class_acc_pct": round(wf_avg_3c, 2) if not np.isnan(wf_avg_3c) else None,
            "avg_directional_only_acc_pct": round(wf_avg_dir, 2) if not np.isnan(wf_avg_dir) else None,
            "folds": fold_reports,
        },
        "holdout": {
            "accuracy_3class_pct": round(holdout_acc * 100, 2),
            "directional_only_acc_pct": round(dir_only * 100, 2) if not np.isnan(dir_only) else None,
            "directional_only_n": int(nonflat.sum()),
            "predicted_dist": dict(zip(DIR_LABELS, np.bincount(y_pred, minlength=3).tolist())),
        },
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2, default=str)

    md = []
    md.append("# Overnight Nifty LSTM — Direction-only (v2, walk-forward)\n")
    md.append(f"**Trained at:** {meta['trained_at']}  \n")
    md.append(f"**Features:** {len(feat_cols)}, **seq_len:** {SEQ_LEN}\n\n")
    md.append("## Walk-forward\n")
    md.append(f"- Avg 3-class accuracy: **{wf_avg_3c:.2f}%**\n")
    md.append(f"- Avg directional-only: **{wf_avg_dir:.2f}%**\n\n")
    md.append("| Fold | Test window | n | 3-class | Dir-only (n) | Predicted dist |\n")
    md.append("|---|---|---:|---:|---|---|\n")
    for r in fold_reports:
        md.append(f"| {r['fold']} | {r['test_window']} | {r['test_n']} | {r['accuracy_3class']}% | "
                  f"{r['directional_only_acc']}% (n={r['directional_only_n']}) | {r['predicted_dist']} |\n")
    md.append(f"\n## Final-model holdout (April 2026)\n")
    md.append(f"- 3-class: **{holdout_acc*100:.1f}%**\n")
    md.append(f"- Dir-only: **{dir_only*100:.1f}%** on n={nonflat.sum()}\n\n")
    md.append(holdout_df.to_markdown(index=False))
    md_path = os.path.join(OUT_DIR, "lstm_walkforward_report.md")
    with open(md_path, "w") as f:
        f.writelines(md)
    print(f"\nSaved: {md_path}")


if __name__ == "__main__":
    main()
