"""
Multi-task LSTM trainer for the overnight Nifty close prediction.

Architecture:
  Input (seq_len=60, n_features) → LSTM(128, return_seq) → Dropout
  → LSTM(64, return_seq) → Dropout → Attention pooling
  → Dense(64, relu) → Dropout
  → 3 heads:
      • reg_logret  (linear)        — predicted log-return
      • cls_dir     (softmax, 3)    — direction (DOWN/FLAT/UP)
      • cls_mag     (softmax, 4)    — magnitude bucket

Joint loss: 1.0 * Huber(reg) + 2.0 * CE(dir) + 1.0 * CE(mag)

Train: 2016 → 2026-03-31  (with last 10% as time-series validation)
Holdout: 2026-04-01 → end (untouched here; evaluated by evaluate_holdout.py)

Run:
    python train_overnight_lstm.py
    python train_overnight_lstm.py --epochs 80 --seq 60
"""
from __future__ import annotations

import argparse
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
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_class_weight


@tf.keras.utils.register_keras_serializable(package="overnight_nifty")
class SumOverTime(tf.keras.layers.Layer):
    """Sums a sequence tensor over the time axis. Serializable replacement for
    the previous Lambda(lambda t: tf.reduce_sum(t, axis=1))."""

    def call(self, x):
        return tf.reduce_sum(x, axis=1)

    def compute_output_shape(self, input_shape):
        return (input_shape[0], input_shape[2])

from feature_engineering import (
    DIR_LABELS, MAG_LABELS, build_features, split_features_targets,
)

THIS_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(THIS_DIR, "data")
RAW_PATH = os.path.join(DATA_DIR, "overnight_raw.parquet")

MODEL_PATH    = os.path.join(THIS_DIR, "overnight_lstm.keras")
SCALER_PATH   = os.path.join(THIS_DIR, "overnight_scaler.pkl")
META_PATH     = os.path.join(THIS_DIR, "overnight_metadata.json")
FEATURES_PATH = os.path.join(DATA_DIR, "overnight_features.parquet")

TRAIN_END = pd.Timestamp("2026-03-31")
HOLDOUT_START = pd.Timestamp("2026-04-01")

DEFAULT_SEQ_LEN = 60
DEFAULT_EPOCHS = 60
DEFAULT_BATCH = 64


def make_sequences(X: np.ndarray, y_logret: np.ndarray, y_dir: np.ndarray,
                   y_mag: np.ndarray, seq_len: int):
    """Build rolling windows. Sequence at index t uses X[t-seq_len+1 : t+1]
    to predict targets at t."""
    n = len(X)
    if n < seq_len:
        raise ValueError(f"Not enough rows ({n}) for seq_len={seq_len}")
    out_X, out_r, out_d, out_m = [], [], [], []
    for t in range(seq_len - 1, n):
        out_X.append(X[t - seq_len + 1 : t + 1])
        out_r.append(y_logret[t])
        out_d.append(y_dir[t])
        out_m.append(y_mag[t])
    return (np.asarray(out_X, dtype=np.float32),
            np.asarray(out_r, dtype=np.float32),
            np.asarray(out_d, dtype=np.int64),
            np.asarray(out_m, dtype=np.int64))


def build_model(seq_len: int, n_features: int) -> tf.keras.Model:
    L2 = tf.keras.regularizers.l2(1e-4)
    inp = tf.keras.layers.Input(shape=(seq_len, n_features), name="seq")
    x = tf.keras.layers.LSTM(64, return_sequences=True, dropout=0.35,
                              kernel_regularizer=L2, recurrent_regularizer=L2)(inp)
    x = tf.keras.layers.LayerNormalization()(x)
    x = tf.keras.layers.LSTM(32, return_sequences=True, dropout=0.35,
                              kernel_regularizer=L2, recurrent_regularizer=L2)(x)
    x = tf.keras.layers.LayerNormalization()(x)

    # Additive attention pooling over time
    attn_scores = tf.keras.layers.Dense(1, activation="tanh", kernel_regularizer=L2)(x)
    attn_weights = tf.keras.layers.Softmax(axis=1, name="attn_weights")(attn_scores)
    context = tf.keras.layers.Multiply()([x, attn_weights])
    pooled = SumOverTime(name="attn_pool")(context)

    h = tf.keras.layers.Dense(32, activation="relu", kernel_regularizer=L2)(pooled)
    h = tf.keras.layers.Dropout(0.4)(h)

    reg_out = tf.keras.layers.Dense(1, name="reg_logret", kernel_regularizer=L2)(h)
    dir_out = tf.keras.layers.Dense(3, activation="softmax", name="cls_dir", kernel_regularizer=L2)(h)
    mag_out = tf.keras.layers.Dense(4, activation="softmax", name="cls_mag", kernel_regularizer=L2)(h)

    model = tf.keras.Model(inputs=inp, outputs=[reg_out, dir_out, mag_out])
    return model


def train(seq_len: int = DEFAULT_SEQ_LEN, epochs: int = DEFAULT_EPOCHS,
          batch_size: int = DEFAULT_BATCH, val_frac: float = 0.10, seed: int = 42):
    np.random.seed(seed)
    tf.random.set_seed(seed)

    print(f"Loading raw data: {RAW_PATH}")
    raw = pd.read_parquet(RAW_PATH)

    print("Building features…")
    feats = build_features(raw)
    feat_cols, X_df, y_df = split_features_targets(feats)
    feats.to_parquet(FEATURES_PATH)
    print(f"  saved feature cache → {FEATURES_PATH}")

    # Split: train through 2026-03-31, holdout from 2026-04-01 (excluded here)
    train_df = feats.loc[feats.index <= TRAIN_END]
    holdout_df = feats.loc[feats.index >= HOLDOUT_START]
    print(f"Train rows: {len(train_df)}  ({train_df.index.min().date()} → {train_df.index.max().date()})")
    print(f"Holdout rows: {len(holdout_df)}  (untouched here — evaluate_holdout.py uses these)")

    X_train_raw = train_df[feat_cols].values.astype(np.float32)
    scaler = StandardScaler().fit(X_train_raw)
    X_train = scaler.transform(X_train_raw)

    # Scale log-return to percent so the regression head trains on a sensible magnitude.
    # At inference we divide by 100 to recover log-return.
    LOGRET_SCALE = 100.0
    y_r = (train_df["y_logret"].values.astype(np.float32) * LOGRET_SCALE)
    y_d = train_df["y_dir"].values.astype(np.int64)
    y_m = train_df["y_mag"].values.astype(np.int64)

    print(f"Building sequences (seq_len={seq_len})…")
    Xs, ys_r, ys_d, ys_m = make_sequences(X_train, y_r, y_d, y_m, seq_len)
    print(f"  sequence shape: {Xs.shape}")

    # Time-series validation: last `val_frac` of sequences
    n = len(Xs)
    n_val = int(n * val_frac)
    Xtr, Xval = Xs[:-n_val], Xs[-n_val:]
    rtr, rval = ys_r[:-n_val], ys_r[-n_val:]
    dtr, dval = ys_d[:-n_val], ys_d[-n_val:]
    mtr, mval = ys_m[:-n_val], ys_m[-n_val:]
    print(f"  train: {len(Xtr)}  val: {len(Xval)}")

    # Mild class weights — sqrt of "balanced" — counter imbalance without over-correcting
    dir_w = np.sqrt(compute_class_weight("balanced", classes=np.array([0, 1, 2]), y=dtr))
    mag_w = np.sqrt(compute_class_weight("balanced", classes=np.array([0, 1, 2, 3]), y=mtr))
    print(f"Class weights — dir: {dict(enumerate(dir_w.round(3)))}, mag: {dict(enumerate(mag_w.round(3)))}")

    sample_w_dir = np.array([dir_w[c] for c in dtr], dtype=np.float32)
    sample_w_mag = np.array([mag_w[c] for c in mtr], dtype=np.float32)
    sample_w_reg = np.ones_like(rtr, dtype=np.float32)

    print("Building model…")
    model = build_model(seq_len, X_train.shape[1])
    # Targets after scaling: y_r in % (std≈1), so Huber delta=1.0 is appropriate
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=5e-4, clipnorm=1.0),
        loss={
            "reg_logret": tf.keras.losses.Huber(delta=1.0),
            "cls_dir":    tf.keras.losses.SparseCategoricalCrossentropy(),
            "cls_mag":    tf.keras.losses.SparseCategoricalCrossentropy(),
        },
        # All three losses are now on comparable O(1) scales; weight dir slightly higher
        loss_weights={"reg_logret": 1.0, "cls_dir": 1.5, "cls_mag": 0.5},
        metrics={
            "reg_logret": [tf.keras.metrics.MeanAbsoluteError(name="mae")],
            "cls_dir":    [tf.keras.metrics.SparseCategoricalAccuracy(name="acc")],
            "cls_mag":    [tf.keras.metrics.SparseCategoricalAccuracy(name="acc")],
        },
    )
    model.summary()

    cbs = [
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=10, restore_best_weights=True, verbose=1),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=4, min_lr=1e-6, verbose=1),
    ]

    print(f"Training (epochs={epochs}, batch={batch_size})…")
    # Keras 3 multi-output sample_weight needs list aligned to output order.
    hist = model.fit(
        Xtr,
        [rtr, dtr, mtr],
        sample_weight=[sample_w_reg, sample_w_dir, sample_w_mag],
        validation_data=(Xval, [rval, dval, mval]),
        epochs=epochs, batch_size=batch_size, callbacks=cbs, verbose=2,
    )

    # ── Save artifacts ────────────────────────────────────────────────────
    model.save(MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)

    final = {k: float(v[-1]) for k, v in hist.history.items()}
    meta = {
        "model_name": "overnight_nifty_lstm",
        "version": "v1",
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "seq_len": seq_len,
        "n_features": int(X_train.shape[1]),
        "feature_columns": feat_cols,
        "dir_labels": DIR_LABELS,
        "mag_labels": MAG_LABELS,
        "logret_scale": LOGRET_SCALE,    # divide model regression output by this to get log-return
        "train_start": str(train_df.index.min().date()),
        "train_end":   str(train_df.index.max().date()),
        "holdout_start": str(HOLDOUT_START.date()),
        "epochs_run": len(hist.history["loss"]),
        "final_metrics": final,
    }
    with open(META_PATH, "w") as fh:
        json.dump(meta, fh, indent=2)
    print(f"\nSaved:\n  model    → {MODEL_PATH}\n  scaler   → {SCALER_PATH}\n  metadata → {META_PATH}")
    print(f"\nFinal val metrics:")
    for k, v in final.items():
        if k.startswith("val_"):
            print(f"  {k}: {v:.5f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq", type=int, default=DEFAULT_SEQ_LEN)
    ap.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    train(seq_len=args.seq, epochs=args.epochs, batch_size=args.batch, seed=args.seed)


if __name__ == "__main__":
    main()
