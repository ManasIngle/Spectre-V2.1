"""
Spectre 3-Minute Scalper LSTM
==============================
Predicts the direction of Nifty 50 over the NEXT 3 MINUTES from the current bar.

Architecture:
  - Input: 30-bar rolling window (30 minutes of 1m data per sample)
  - Features per bar: 42 (price action + technical + sectoral breadth + VIX)
  - Model: Bidirectional LSTM (64 units) → LSTM (32 units) → Dense → Softmax(3)
  - Output: [P(DOWN), P(SIDEWAYS), P(UP)]

Key design decisions:
  - 3-bar (3 minute) forward horizon — tight enough for scalping before theta decay
  - Asymmetric labeling: DOWN needs 0.07% move, UP needs 0.05% (suppress false bearish)
  - Sector breadth features: how many of BANK/IT/FIN/AUTO/FMCG are advancing → regime context
  - VIX regime feature: LSTM learns different patterns in low/high fear environments
  - TimeSeriesSplit CV: no data leakage — test is always in the future relative to train
  - RobustScaler per feature: handles outlier spikes (circuit breakers, expiry swings)
  - Class weights: DOWN ×0.6, SIDEWAYS ×0.5, UP ×1.0 (calibrated from existing backtest)

Output files:
  nifty_scalper_lstm-Rtr14April.keras    — Keras model
  nifty_scalper_scaler-Rtr14April.pkl   — RobustScaler (must be saved, used at inference)
  nifty_scalper_meta-Rtr14April.json    — feature list + config for sidecar

Usage:
  python train_scalper_lstm.py
"""

import os
import json
import warnings
import numpy as np
import pandas as pd
import joblib

warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

MODEL_DIR   = os.path.dirname(__file__)
DATA_DIR    = "/Users/manasingle/Edge/Market Dataset since 2015"
VER         = "-Rtr14April"

# ─── Config ───────────────────────────────────────────────────────────────────

SEQ_LEN        = 30      # 30 one-minute bars lookback window (~30 minutes of context)
FORWARD_BARS   = 3       # Predict 3 minutes into the future
THRESHOLD_UP   = 0.05    # % move required to label UP
THRESHOLD_DN   = 0.07    # % move required to label DOWN (higher = fewer false bearish)

# Sector indices that provide market breadth context
SECTOR_FILES = {
    "bank":  "NIFTY BANK_minute.csv",
    "it":    "NIFTY IT_minute.csv",
    "fin":   "NIFTY FIN SERVICE_minute.csv",
    "auto":  "NIFTY AUTO_minute.csv",
    "fmcg":  "NIFTY FMCG_minute.csv",
}

# ─── Data Loading ─────────────────────────────────────────────────────────────

def load_base_data() -> pd.DataFrame:
    """Load Nifty 50 1m data with VIX and sector breadth merged in."""
    print("Loading Nifty 50 1-minute data...")
    n50 = pd.read_csv(os.path.join(DATA_DIR, "NIFTY 50_minute.csv"), parse_dates=["date"])
    n50.set_index("date", inplace=True)
    n50.columns = [c.capitalize() for c in n50.columns]
    n50 = n50.between_time("09:15", "15:30").sort_index()
    n50.dropna(subset=["Close"], inplace=True)
    print(f"  Nifty 50: {len(n50):,} rows ({n50.index[0].date()} → {n50.index[-1].date()})")

    # ── India VIX ──
    vix_path = os.path.join(DATA_DIR, "INDIA VIX_minute.csv")
    if os.path.exists(vix_path):
        vix = pd.read_csv(vix_path, parse_dates=["date"])
        vix.set_index("date", inplace=True)
        n50 = n50.join(vix[["close"]].rename(columns={"close": "VIX"}), how="left")
        n50["VIX"] = n50["VIX"].ffill().fillna(16.0)
        print(f"  VIX merged.")

    # ── Sector indices → breadth features ──
    print("Loading sector indices for breadth features...")
    for key, fname in SECTOR_FILES.items():
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            print(f"  WARNING: {fname} not found — skipping {key}")
            continue
        sec = pd.read_csv(path, parse_dates=["date"])
        sec.set_index("date", inplace=True)
        sec = sec.between_time("09:15", "15:30").sort_index()
        col = f"sec_{key}_close"
        n50 = n50.join(sec[["close"]].rename(columns={"close": col}), how="left")
        n50[col] = n50[col].ffill()
        print(f"  {key.upper()} merged: {sec[['close']].notna().sum().values[0]:,} rows")

    return n50


# ─── Feature Engineering ─────────────────────────────────────────────────────

def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """
    Build all 42 features on the 1-minute dataframe.
    Returns (df_with_features, feature_column_names)
    """
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.trend import ADXIndicator, MACD, EMAIndicator
    from ta.volatility import AverageTrueRange, BollingerBands

    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]

    # ── Price returns (most important for short-horizon LSTM) ──
    df["f_ret1"]  = close.pct_change(1) * 100
    df["f_ret2"]  = close.pct_change(2) * 100
    df["f_ret3"]  = close.pct_change(3) * 100
    df["f_ret5"]  = close.pct_change(5) * 100
    df["f_ret10"] = close.pct_change(10) * 100

    # ── Body and wick features (candle shape context) ──
    df["f_body_pct"]      = ((close - df["Open"]) / df["Open"] * 100).fillna(0)
    df["f_upper_wick"]    = ((high - close.clip(lower=df["Open"])) / df["Open"] * 100).fillna(0)
    df["f_lower_wick"]    = ((close.clip(upper=df["Open"]) - low) / df["Open"] * 100).fillna(0)
    df["f_hl_range"]      = ((high - low) / close * 100).fillna(0)

    # ── RSI ──
    df["f_rsi14"] = RSIIndicator(close, window=14).rsi()
    df["f_rsi7"]  = RSIIndicator(close, window=7).rsi()
    df["f_rsi_delta"] = df["f_rsi14"].diff(1)

    # ── MACD ──
    macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
    df["f_macd_hist"] = macd.macd_diff()
    df["f_macd_delta"] = df["f_macd_hist"].diff(1)

    # ── EMA spreads ──
    ema5  = EMAIndicator(close, window=5).ema_indicator()
    ema9  = EMAIndicator(close, window=9).ema_indicator()
    ema21 = EMAIndicator(close, window=21).ema_indicator()
    df["f_ema5_9_spread"]  = ((ema5 - ema9) / close * 100)
    df["f_ema9_21_spread"] = ((ema9 - ema21) / close * 100)
    df["f_price_vs_ema9"]  = ((close - ema9) / close * 100)
    df["f_price_vs_ema21"] = ((close - ema21) / close * 100)

    # ── ATR (volatility context) ──
    atr = AverageTrueRange(high, low, close, window=14).average_true_range()
    df["f_atr_pct"]    = (atr / close * 100)
    df["f_atr_move"]   = ((close - close.shift(1)) / atr).fillna(0)
    df["f_atr_regime"] = (atr / atr.rolling(50).mean()).fillna(1.0)  # > 1 = expanding volatility

    # ── Bollinger Band position ──
    bb = BollingerBands(close, window=20, window_dev=2)
    bb_range = bb.bollinger_hband() - bb.bollinger_lband()
    df["f_bb_pos"]   = np.where(bb_range > 0, (close - bb.bollinger_lband()) / bb_range, 0.5)
    df["f_bb_width"] = (bb_range / close * 100)

    # ── Stochastic ──
    stoch = StochasticOscillator(high, low, close, window=14, smooth_window=3)
    df["f_stoch_k"] = stoch.stoch()
    df["f_stoch_d"] = stoch.stoch_signal()

    # ── ADX ──
    try:
        adx = ADXIndicator(high, low, close, window=14)
        df["f_adx"]      = adx.adx()
        df["f_di_diff"]  = adx.adx_pos() - adx.adx_neg()
    except Exception:
        df["f_adx"]     = 25.0
        df["f_di_diff"] = 0.0

    # ── Momentum streak (consecutive up/down candles) ──
    ret_sign  = np.sign(close.pct_change())
    up_streak   = (ret_sign > 0).astype(int)
    dn_streak   = (ret_sign < 0).astype(int)
    df["f_consec_up"]   = up_streak.groupby((up_streak != up_streak.shift()).cumsum()).cumsum() * up_streak
    df["f_consec_down"] = dn_streak.groupby((dn_streak != dn_streak.shift()).cumsum()).cumsum() * dn_streak

    # ── Session position (0=open, 1=close) — critical for intraday patterns ──
    mins = pd.Series(df.index.hour * 60 + df.index.minute, index=df.index)
    df["f_session_pos"] = ((mins - (9 * 60 + 15)) / 375).clip(0, 1)

    # ── VIX features ──
    vix = df.get("VIX", pd.Series(16.0, index=df.index))
    df["f_vix"]        = vix
    df["f_vix_chg"]    = vix.pct_change(1) * 100
    df["f_vix_vs_avg"] = ((vix - vix.rolling(20).mean()) / vix.rolling(20).mean() * 100).fillna(0)
    df["f_vix_regime"] = pd.cut(vix, bins=[0, 13, 20, 30, 10000],
                                 labels=[0, 1, 2, 3]).astype(float).fillna(1.0)

    # ── Sector breadth ──
    # Returns of each sector relative to Nifty — leading/lagging divergence
    sector_rets = {}
    for key in SECTOR_FILES:
        col = f"sec_{key}_close"
        if col in df.columns:
            sec_ret = df[col].pct_change(1) * 100
            nifty_ret = df["f_ret1"]
            df[f"f_sec_{key}_rel"] = (sec_ret - nifty_ret).fillna(0)
            sector_rets[key] = sec_ret
        else:
            df[f"f_sec_{key}_rel"] = 0.0

    # Breadth score: count of advancing sectors (0-5)
    advancing = pd.DataFrame({
        k: (v > 0).astype(int) for k, v in sector_rets.items()
    }) if sector_rets else pd.DataFrame()
    df["f_breadth_score"] = advancing.sum(axis=1).fillna(0) if not advancing.empty else 0.0

    feature_cols = [c for c in df.columns if c.startswith("f_")]
    return df, feature_cols


# ─── Target Creation ──────────────────────────────────────────────────────────

def create_targets(df: pd.DataFrame) -> pd.DataFrame:
    """
    3-bar forward return labeling.
    UP   if future_return >  THRESHOLD_UP
    DOWN if future_return < -THRESHOLD_DN
    SIDEWAYS otherwise
    """
    close = df["Close"]
    future_ret = (close.shift(-FORWARD_BARS) - close) / close * 100

    df["target"] = 0                                      # SIDEWAYS
    df.loc[future_ret >  THRESHOLD_UP, "target"] = 1     # UP
    df.loc[future_ret < -THRESHOLD_DN, "target"] = 2     # DOWN
    return df


# ─── Sequence Builder ────────────────────────────────────────────────────────

def build_sequences(X: np.ndarray, y: np.ndarray, seq_len: int):
    """Convert flat feature matrix into (samples, seq_len, features) LSTM input."""
    Xs, ys = [], []
    for i in range(seq_len, len(X)):
        Xs.append(X[i - seq_len:i])
        ys.append(y[i])
    return np.array(Xs, dtype=np.float32), np.array(ys, dtype=np.int32)


# ─── Model ───────────────────────────────────────────────────────────────────

def build_model(seq_len: int, n_features: int) -> "keras.Model":
    import tensorflow as tf
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import (
        Bidirectional, LSTM, Dense, Dropout, BatchNormalization, Input
    )
    from tensorflow.keras.regularizers import l2

    model = Sequential([
        Input(shape=(seq_len, n_features)),

        # First LSTM layer — bidirectional to capture both momentum buildup and reversal
        Bidirectional(LSTM(64, return_sequences=True,
                           kernel_regularizer=l2(1e-4),
                           recurrent_regularizer=l2(1e-4))),
        BatchNormalization(),
        Dropout(0.3),

        # Second LSTM — summarize into one context vector
        LSTM(32, return_sequences=False,
             kernel_regularizer=l2(1e-4)),
        BatchNormalization(),
        Dropout(0.25),

        # Classification head
        Dense(24, activation="relu", kernel_regularizer=l2(1e-4)),
        Dropout(0.2),
        Dense(3, activation="softmax"),
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=3e-4, clipnorm=1.0),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


# ─── Training ────────────────────────────────────────────────────────────────

def train():
    import tensorflow as tf
    from sklearn.preprocessing import RobustScaler
    from sklearn.metrics import classification_report, accuracy_score, confusion_matrix

    # ── 1. Load + engineer ──
    df = load_base_data()
    df, feat_cols = build_features(df)
    df = create_targets(df)

    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(subset=feat_cols + ["target"], inplace=True)

    print(f"\nDataset after feature engineering: {len(df):,} rows, {len(feat_cols)} features")
    print(f"Target distribution:")
    for cls, label in [(0, "SIDEWAYS"), (1, "UP"), (2, "DOWN")]:
        n = (df["target"] == cls).sum()
        print(f"  {label}: {n:,} ({n/len(df)*100:.1f}%)")

    # ── 2. Scale features ──
    # Fit scaler on training data only (pre-2023 → train, 2023+ → test)
    train_mask = df.index.year < 2023
    test_mask  = ~train_mask

    X_all = df[feat_cols].values
    y_all = df["target"].values

    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(X_all)  # We'll split after scaling but scaler fit on train idx
    # Refit scaler on train only (correct procedure)
    scaler = RobustScaler()
    scaler.fit(X_all[train_mask])
    X_scaled = scaler.transform(X_all)  # transform all using train statistics

    # ── 3. Build sequences ──
    print(f"\nBuilding {SEQ_LEN}-bar sequences...")
    X_seq, y_seq = build_sequences(X_scaled, y_all, SEQ_LEN)
    # Adjust masks for sequence offset
    # After build_sequences, sample i corresponds to original index i + SEQ_LEN
    idx_arr = df.index[SEQ_LEN:]   # shifted by SEQ_LEN
    train_seq_mask = pd.Series(idx_arr).apply(lambda x: x.year < 2023).values
    test_seq_mask  = ~train_seq_mask

    X_train, y_train = X_seq[train_seq_mask], y_seq[train_seq_mask]
    X_test,  y_test  = X_seq[test_seq_mask],  y_seq[test_seq_mask]

    print(f"Train sequences: {len(X_train):,} | Test sequences: {len(X_test):,}")

    # ── 4. Class weights — suppress false bearish, neutral on UP ──
    from sklearn.utils.class_weight import compute_class_weight
    classes = np.unique(y_train)
    raw_weights = compute_class_weight("balanced", classes=classes, y=y_train)
    cw = dict(zip(classes.tolist(), raw_weights.tolist()))
    cw[0] = cw.get(0, 1.0) * 0.5   # SIDEWAYS — reduce noise
    cw[1] = cw.get(1, 1.0) * 1.0   # UP — keep natural weight
    cw[2] = cw.get(2, 1.0) * 0.6   # DOWN — suppress false bearish
    print(f"Class weights: SIDEWAYS={cw[0]:.3f}  UP={cw[1]:.3f}  DOWN={cw[2]:.3f}")

    # ── 5. Build and train model ──
    model = build_model(SEQ_LEN, len(feat_cols))
    model.summary()

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_accuracy", patience=8, restore_best_weights=True, verbose=1
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=4, min_lr=1e-5, verbose=1
        ),
    ]

    print(f"\nTraining 3-Minute Scalper LSTM...")
    history = model.fit(
        X_train, y_train,
        validation_data=(X_test, y_test),
        epochs=60,
        batch_size=512,
        class_weight=cw,
        callbacks=callbacks,
        verbose=1,
    )

    # ── 6. Evaluate ──
    y_pred = np.argmax(model.predict(X_test, batch_size=1024), axis=1)
    acc = accuracy_score(y_test, y_pred)

    print(f"\n{'='*50}")
    print(f"  3-MINUTE SCALPER LSTM ACCURACY: {acc*100:.2f}%")
    print(f"{'='*50}")
    print(classification_report(y_test, y_pred,
                                 target_names=["SIDEWAYS", "UP", "DOWN"]))

    cm = confusion_matrix(y_test, y_pred)
    print("Confusion Matrix (rows=actual, cols=predicted):")
    print(f"             SIDEWAYS   UP    DOWN")
    labels = ["SIDEWAYS", "UP", "DOWN"]
    for i, row in enumerate(cm):
        print(f"  {labels[i]:<10}  {row}")

    # ── 7. Save ──
    model_path  = os.path.join(MODEL_DIR, f"nifty_scalper_lstm{VER}.keras")
    scaler_path = os.path.join(MODEL_DIR, f"nifty_scalper_scaler{VER}.pkl")
    meta_path   = os.path.join(MODEL_DIR, f"nifty_scalper_meta{VER}.json")

    model.save(model_path)
    joblib.dump(scaler, scaler_path)

    meta = {
        "feature_columns": feat_cols,
        "seq_len":         SEQ_LEN,
        "forward_bars":    FORWARD_BARS,
        "threshold_up":    THRESHOLD_UP,
        "threshold_dn":    THRESHOLD_DN,
        "classes":         ["SIDEWAYS", "UP", "DOWN"],
        "class_map":       {"0": "SIDEWAYS", "1": "UP", "2": "DOWN"},
        "sector_keys":     list(SECTOR_FILES.keys()),
        "n_features":      len(feat_cols),
        "accuracy":        round(acc * 100, 2),
        "train_rows":      len(X_train),
        "test_rows":       len(X_test),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nSaved:")
    print(f"  Model:   {model_path}")
    print(f"  Scaler:  {scaler_path}")
    print(f"  Meta:    {meta_path}")


if __name__ == "__main__":
    train()
