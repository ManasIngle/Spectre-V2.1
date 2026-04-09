"""
Train XGBoost + LSTM models for multiple timeframes.
Produces separate model files for each timeframe so they can be used
as a multi-TF governor system (5m trigger, 15m confirmation, 1h bias).

Usage:
    python train_multitf.py              # Train all timeframes
    python train_multitf.py --tf 5m      # Train only 5-minute model
    python train_multitf.py --tf 15m     # Train only 15-minute model
    python train_multitf.py --tf 1h      # Retrain the hourly model

Outputs per timeframe:
    nifty_direction_model_{tf}.pkl       XGBoost model
    nifty_lstm_model_{tf}.keras          LSTM model
    lstm_scaler_{tf}.pkl                 LSTM feature scaler
    model_metadata_{tf}.json             XGBoost metadata
    lstm_metadata_{tf}.json              LSTM metadata
"""

import os
import sys
import io
import json
import argparse
import numpy as np
import pandas as pd
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix
from sklearn.preprocessing import RobustScaler
from sklearn.utils.class_weight import compute_class_weight

# Fix Windows encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Suppress TF warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

MODEL_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(MODEL_DIR, "data")

# ─── Timeframe Configuration ─────────────────────────────────────────────────
TF_CONFIGS = {
    "5m": {
        "data_file": "nifty_5m.csv",
        "forward_bars": 6,        # 6 × 5m = 30 minutes ahead
        "threshold_pct": 0.08,    # Tighter threshold for short-term
        "lstm_seq_len": 30,       # 30 × 5m = 2.5 hours lookback
        "role": "Scalp trigger (30-min prediction)",
    },
    "15m": {
        "data_file": "nifty_15m.csv",
        "forward_bars": 6,        # 6 × 15m = 90 minutes ahead
        "threshold_pct": 0.12,    # Medium threshold
        "lstm_seq_len": 24,       # 24 × 15m = 6 hours lookback
        "role": "Swing confirmation (90-min prediction)",
    },
    "1h": {
        "data_file": "nifty_1h.csv",
        "forward_bars": 6,        # 6 × 1h = 6 hours ahead
        "threshold_pct": 0.15,    # Original threshold
        "lstm_seq_len": 30,       # 30 × 1h = 30 hours lookback
        "role": "Trend bias (6-hour prediction)",
    },
}


def load_data(tf: str) -> pd.DataFrame:
    """Load OHLCV data for the specified timeframe."""
    config = TF_CONFIGS[tf]
    path = os.path.join(DATA_DIR, config["data_file"])
    if not os.path.exists(path):
        raise FileNotFoundError(f"Data file not found: {path}\nRun data_downloader.py first.")
    
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.dropna(subset=['Close'], inplace=True)
    print(f"Loaded {tf} data: {len(df)} rows from {path}")
    return df


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add all XGBoost features (same pipeline as feature_builder.py)."""
    from ta.trend import ADXIndicator, MACD, EMAIndicator
    from ta.momentum import RSIIndicator
    from ta.volatility import BollingerBands, AverageTrueRange
    
    close = df['Close'].copy()
    high = df['High'].copy()
    low = df['Low'].copy()
    volume = df['Volume'].copy()

    # RSI
    df['feat_rsi'] = RSIIndicator(close, window=14).rsi()

    # ADX
    try:
        adx_ind = ADXIndicator(high, low, close, window=14)
        df['feat_adx'] = adx_ind.adx()
        df['feat_di_plus'] = adx_ind.adx_pos()
        df['feat_di_minus'] = adx_ind.adx_neg()
        df['feat_di_diff'] = df['feat_di_plus'] - df['feat_di_minus']
    except Exception:
        df['feat_adx'] = 0
        df['feat_di_plus'] = 0
        df['feat_di_minus'] = 0
        df['feat_di_diff'] = 0

    # MACD histogram
    df['feat_macd_hist'] = MACD(close).macd_diff()

    # EMA 9/21 spread
    ema9 = EMAIndicator(close, window=9).ema_indicator()
    ema21 = EMAIndicator(close, window=21).ema_indicator()
    df['feat_ema_spread'] = ((ema9 - ema21) / close) * 100

    # VWAP deviation (volume-weighted MA proxy)
    vw_avg = (close * volume).rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)
    df['feat_vwap_dev'] = ((close - vw_avg) / close * 100).fillna(0)

    # Supertrend direction
    atr = AverageTrueRange(high, low, close, window=10).average_true_range()
    hl2 = (high + low) / 2
    upper = hl2 + 2 * atr
    lower = hl2 - 2 * atr
    df['feat_st_direction'] = np.where(close > upper.shift(1), 1,
                              np.where(close < lower.shift(1), -1, 0))

    # Volume
    avg20 = volume.rolling(20).mean()
    df['feat_rel_vol'] = np.where(avg20 > 0, volume / avg20, 1)
    avg5 = volume.rolling(5).mean()
    df['feat_vol_trend'] = np.where(avg20 > 0, avg5 / avg20, 1)

    # Momentum
    df['feat_roc_6'] = close.pct_change(6) * 100
    df['feat_roc_12'] = close.pct_change(12) * 100

    # Bollinger position
    bb = BollingerBands(close, window=20, window_dev=2)
    bb_range = bb.bollinger_hband() - bb.bollinger_lband()
    df['feat_bb_pos'] = np.where(bb_range > 0, (close - bb.bollinger_lband()) / bb_range, 0.5)

    # ATR move
    atr14 = AverageTrueRange(high, low, close, window=14).average_true_range()
    df['feat_atr_move'] = np.where(atr14 > 0, (close - close.shift(1)) / atr14, 0)

    # Lagged returns
    df['feat_ret_1'] = close.pct_change(1) * 100
    df['feat_ret_2'] = close.pct_change(2) * 100
    df['feat_ret_3'] = close.pct_change(3) * 100

    # Slow indicators (higher-TF approximation)
    df['feat_slow_rsi'] = RSIIndicator(close, window=42).rsi()
    try:
        macd_slow = MACD(close, window_slow=52, window_fast=24, window_sign=18)
        df['feat_slow_macd_hist'] = macd_slow.macd_diff()
    except Exception:
        df['feat_slow_macd_hist'] = 0

    atr_slow = AverageTrueRange(high, low, close, window=30).average_true_range()
    hl2 = (high + low) / 2
    upper_s = hl2 + 2 * atr_slow
    lower_s = hl2 - 2 * atr_slow
    df['feat_slow_st_dir'] = np.where(close > upper_s.shift(1), 1,
                             np.where(close < lower_s.shift(1), -1, 0))

    # Time features
    df['feat_hour'] = df.index.hour
    df['feat_minutes_since_open'] = (df.index.hour - 9) * 60 + df.index.minute - 15
    df['feat_day_of_week'] = df.index.dayofweek

    # Regime
    atr20 = AverageTrueRange(high, low, close, window=20).average_true_range()
    df['feat_volatility'] = np.where(close > 0, (atr20 / close) * 100, 0)
    df['feat_trend_strength'] = df['feat_adx'].fillna(0)

    # Futures premium proxy
    ema50 = close.ewm(span=50).mean()
    df['feat_futures_premium_proxy'] = np.where(close > 0, ((close - ema50) / close) * 100, 0)
    df['feat_premium_change_rate'] = df['feat_futures_premium_proxy'].diff(6)

    # Note: equity contribution features are set to 0 for sub-hourly models
    # (contributor data alignment is unreliable at 5m/15m granularity)
    df['feat_equity_weighted_ret'] = 0
    df['feat_equity_advance_pct'] = 0
    df['feat_equity_momentum'] = 0

    return df


FEATURE_COLUMNS = [
    'feat_rsi', 'feat_adx', 'feat_di_plus', 'feat_di_minus', 'feat_di_diff',
    'feat_macd_hist', 'feat_ema_spread', 'feat_vwap_dev', 'feat_st_direction',
    'feat_rel_vol', 'feat_vol_trend',
    'feat_roc_6', 'feat_roc_12', 'feat_bb_pos', 'feat_atr_move',
    'feat_ret_1', 'feat_ret_2', 'feat_ret_3',
    'feat_slow_rsi', 'feat_slow_macd_hist', 'feat_slow_st_dir',
    'feat_equity_weighted_ret', 'feat_equity_advance_pct', 'feat_equity_momentum',
    'feat_hour', 'feat_minutes_since_open', 'feat_day_of_week',
    'feat_volatility', 'feat_trend_strength',
    'feat_futures_premium_proxy', 'feat_premium_change_rate',
]


def create_target(df: pd.DataFrame, forward_bars: int, threshold_pct: float) -> pd.DataFrame:
    """Create direction target."""
    close = df['Close']
    future_return = (close.shift(-forward_bars) - close) / close * 100
    df['target'] = 0
    df.loc[future_return > threshold_pct, 'target'] = 1
    df.loc[future_return < -threshold_pct, 'target'] = -1
    return df


def train_xgboost(tf: str):
    """Train XGBoost model for a specific timeframe."""
    config = TF_CONFIGS[tf]
    print(f"\n{'='*60}")
    print(f"Spectre — XGBoost Training [{tf.upper()}]")
    print(f"Role: {config['role']}")
    print(f"{'='*60}")

    df = load_data(tf)
    df = add_features(df)
    df = create_target(df, config['forward_bars'], config['threshold_pct'])

    # Clean
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(subset=FEATURE_COLUMNS + ['target'], inplace=True)

    X = df[FEATURE_COLUMNS].values
    y = df['target'].values + 1  # -1→0, 0→1, 1→2

    print(f"\nDataset: {len(X)} samples, {len(FEATURE_COLUMNS)} features")
    for cls, label in [(0, "DOWN"), (1, "SIDEWAYS"), (2, "UP")]:
        count = (y == cls).sum()
        print(f"  {label}: {count} ({count/len(y)*100:.1f}%)")

    # Chronological split
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    print(f"\nTrain: {len(X_train)}, Test: {len(X_test)}")

    # Class weights
    class_counts = np.bincount(y_train.astype(int))
    total = len(y_train)
    n_classes = len(class_counts)
    class_weights = {i: total / (n_classes * c) if c > 0 else 1.0
                     for i, c in enumerate(class_counts)}
    sample_weights = np.array([class_weights[int(yi)] for yi in y_train])

    # Hyperparameter Tuning using RandomizedSearchCV
    from sklearn.model_selection import RandomizedSearchCV

    param_dist = {
        'n_estimators': [200, 300, 400],
        'max_depth': [4, 6, 8, 10],
        'learning_rate': [0.01, 0.05, 0.1, 0.2],
        'subsample': [0.6, 0.8, 1.0],
        'colsample_bytree': [0.6, 0.8, 1.0],
        'reg_alpha': [0, 0.1, 0.5, 1.0],
        'reg_lambda': [0.1, 1.0, 5.0]
    }
    
    print("\nStarting Hyperparameter Tuning...")
    base_model = XGBClassifier(
        random_state=42, 
        n_jobs=-1,
        eval_metric='mlogloss',
        use_label_encoder=False
    )
    
    random_search = RandomizedSearchCV(
        base_model, param_distributions=param_dist,
        n_iter=15, scoring='accuracy', cv=TimeSeriesSplit(n_splits=3), 
        random_state=42, n_jobs=-1, verbose=1
    )
    
    random_search.fit(X_train, y_train, sample_weight=sample_weights)
    print(f"\nBest Parameters found: {random_search.best_params_}")
    
    model = random_search.best_estimator_

    # Final detailed fit with the best model on test set to get the eval curve
    model.fit(
        X_train, y_train,
        sample_weight=sample_weights,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # Evaluate
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    labels = ["DOWN", "SIDEWAYS", "UP"]
    print(f"\nAccuracy: {accuracy:.4f}")
    print(classification_report(y_test, y_pred, target_names=labels))

    cm = confusion_matrix(y_test, y_pred)
    print(f"Confusion Matrix:")
    print(pd.DataFrame(cm, index=labels, columns=labels).to_string())

    # Feature importance
    importances = model.feature_importances_
    feat_imp = sorted(zip(FEATURE_COLUMNS, importances), key=lambda x: x[1], reverse=True)
    print(f"\nTop 10 Features:")
    for name, imp in feat_imp[:10]:
        print(f"  {name}: {imp:.4f}")

    # Save
    suffix = f"_{tf}" if tf != "1h" else ""
    model_path = os.path.join(MODEL_DIR, f"nifty_direction_model{suffix}.pkl")
    joblib.dump(model, model_path)
    print(f"\nModel saved: {model_path}")

    meta = {
        "timeframe": tf,
        "role": config["role"],
        "feature_columns": FEATURE_COLUMNS,
        "class_mapping": {"0": "DOWN", "1": "SIDEWAYS", "2": "UP"},
        "target_mapping": {"DOWN": -1, "SIDEWAYS": 0, "UP": 1},
        "accuracy": round(accuracy, 4),
        "n_training_samples": len(X_train),
        "n_test_samples": len(X_test),
        "threshold_pct": config["threshold_pct"],
        "forward_bars": config["forward_bars"],
    }
    meta_path = os.path.join(MODEL_DIR, f"model_metadata{suffix}.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata saved: {meta_path}")

    return model, accuracy


def train_lstm(tf: str):
    """Train LSTM model for a specific timeframe."""
    config = TF_CONFIGS[tf]
    seq_len = config["lstm_seq_len"]

    print(f"\n{'='*60}")
    print(f"Spectre — LSTM Training [{tf.upper()}]")
    print(f"Role: {config['role']}")
    print(f"{'='*60}")

    df = load_data(tf)

    # Create LSTM features (same as train_lstm.py)
    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values
    opn = df['Open'].values
    volume = df['Volume'].values

    features = np.column_stack([
        np.concatenate([[0], np.diff(close) / np.maximum(close[:-1], 1) * 100]),
        (high - low) / np.maximum(close, 1) * 100,
        (close - opn) / np.maximum(close, 1) * 100,
        (high - np.maximum(close, opn)) / np.maximum(close, 1) * 100,
        (np.minimum(close, opn) - low) / np.maximum(close, 1) * 100,
        np.concatenate([[1], volume[1:] / np.maximum(volume[:-1], 1)]),
        np.where(high - low > 0, (close - low) / (high - low), 0.5),
        np.concatenate([[0], (opn[1:] - close[:-1]) / np.maximum(close[:-1], 1) * 100]),
    ])

    print(f"Feature matrix: {features.shape}")

    # Scale
    scaler = RobustScaler()
    features_scaled = scaler.fit_transform(features)

    # Create sequences
    forward_bars = config["forward_bars"]
    threshold = config["threshold_pct"]
    X, y = [], []
    for i in range(seq_len, len(features_scaled) - forward_bars):
        X.append(features_scaled[i - seq_len:i])
        current = close[i]
        future = close[i + forward_bars]
        pct_change = (future - current) / current * 100
        if pct_change > threshold:
            y.append(2)   # UP
        elif pct_change < -threshold:
            y.append(0)   # DOWN
        else:
            y.append(1)   # SIDEWAYS

    X = np.array(X)
    y = np.array(y)
    print(f"Sequences: {len(X)} (window={seq_len}, forward={forward_bars})")

    for cls, label in [(0, "DOWN"), (1, "SIDEWAYS"), (2, "UP")]:
        count = (y == cls).sum()
        print(f"  {label}: {count} ({count/len(y)*100:.1f}%)")

    # Split
    split = int(len(X) * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]
    print(f"\nTrain: {len(X_train)}, Test: {len(X_test)}")

    if len(X_train) < 500:
        print(f"\n⚠️ WARNING: Only {len(X_train)} training samples — LSTM may underperform.")
        print("Consider downloading more data or using XGBoost only for this timeframe.\n")

    # Class weights
    classes = np.unique(y_train)
    weights = compute_class_weight('balanced', classes=classes, y=y_train)
    class_weight_dict = dict(zip(classes.astype(int), weights))

    # Build model
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
    from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

    model = Sequential([
        LSTM(64, return_sequences=True, input_shape=(X_train.shape[1], X_train.shape[2])),
        Dropout(0.3),
        BatchNormalization(),
        LSTM(32, return_sequences=False),
        Dropout(0.3),
        BatchNormalization(),
        Dense(32, activation='relu'),
        Dropout(0.2),
        Dense(3, activation='softmax'),
    ])

    model.compile(optimizer='adam', loss='sparse_categorical_crossentropy', metrics=['accuracy'])
    model.summary()

    callbacks = [
        EarlyStopping(monitor='val_loss', patience=8, restore_best_weights=True),
        ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=4, min_lr=1e-6),
    ]

    history = model.fit(
        X_train, y_train,
        validation_data=(X_test, y_test),
        epochs=50,
        batch_size=32,
        class_weight=class_weight_dict,
        callbacks=callbacks,
        verbose=1,
    )

    # Evaluate
    y_pred = np.argmax(model.predict(X_test), axis=1)
    accuracy = accuracy_score(y_test, y_pred)
    labels = ["DOWN", "SIDEWAYS", "UP"]
    print(f"\nLSTM Accuracy: {accuracy:.4f}")
    print(classification_report(y_test, y_pred, target_names=labels))

    # Save
    suffix = f"_{tf}" if tf != "1h" else ""
    model_path = os.path.join(MODEL_DIR, f"nifty_lstm_model{suffix}.keras")
    model.save(model_path)
    
    scaler_path = os.path.join(MODEL_DIR, f"lstm_scaler{suffix}.pkl")
    joblib.dump(scaler, scaler_path)

    meta = {
        "timeframe": tf,
        "role": config["role"],
        "sequence_length": seq_len,
        "n_features": X_train.shape[2],
        "feature_names": [
            "return_pct", "hl_range_pct", "oc_body_pct", "upper_shadow_pct",
            "lower_shadow_pct", "volume_change_ratio", "close_position", "gap_pct"
        ],
        "class_mapping": {"0": "DOWN", "1": "SIDEWAYS", "2": "UP"},
        "accuracy": round(float(accuracy), 4),
        "n_training_samples": len(X_train),
        "n_test_samples": len(X_test),
        "epochs_trained": len(history.history['loss']),
        "best_val_loss": round(float(min(history.history['val_loss'])), 4),
        "threshold_pct": config["threshold_pct"],
        "forward_bars": config["forward_bars"],
    }
    meta_path = os.path.join(MODEL_DIR, f"lstm_metadata{suffix}.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nSaved: {model_path}, {scaler_path}, {meta_path}")
    return model, accuracy


def main():
    parser = argparse.ArgumentParser(description="Spectre Multi-TF Model Training")
    parser.add_argument("--tf", choices=["5m", "15m", "1h", "all"], default="all",
                        help="Timeframe to train (default: all)")
    parser.add_argument("--xgb-only", action="store_true",
                        help="Train only XGBoost (skip LSTM)")
    parser.add_argument("--lstm-only", action="store_true",
                        help="Train only LSTM (skip XGBoost)")
    args = parser.parse_args()

    timeframes = list(TF_CONFIGS.keys()) if args.tf == "all" else [args.tf]

    results = {}
    for tf in timeframes:
        print(f"\n{'#'*60}")
        print(f"#  TIMEFRAME: {tf.upper()}")
        print(f"#  {TF_CONFIGS[tf]['role']}")
        print(f"{'#'*60}")

        tf_results = {}

        if not args.lstm_only:
            try:
                _, acc = train_xgboost(tf)
                tf_results["xgb_accuracy"] = acc
            except Exception as e:
                print(f"\n❌ XGBoost {tf} failed: {e}")
                tf_results["xgb_error"] = str(e)

        if not args.xgb_only:
            try:
                _, acc = train_lstm(tf)
                tf_results["lstm_accuracy"] = acc
            except Exception as e:
                print(f"\n❌ LSTM {tf} failed: {e}")
                tf_results["lstm_error"] = str(e)

        results[tf] = tf_results

    # Summary
    print(f"\n\n{'='*60}")
    print("TRAINING SUMMARY")
    print(f"{'='*60}")
    for tf, res in results.items():
        print(f"\n  {tf.upper()} ({TF_CONFIGS[tf]['role']}):")
        if "xgb_accuracy" in res:
            print(f"    XGBoost: {res['xgb_accuracy']:.4f}")
        if "lstm_accuracy" in res:
            print(f"    LSTM:    {res['lstm_accuracy']:.4f}")
        if "xgb_error" in res:
            print(f"    XGBoost: FAILED — {res['xgb_error']}")
        if "lstm_error" in res:
            print(f"    LSTM:    FAILED — {res['lstm_error']}")
    print(f"\n{'='*60}")


if __name__ == "__main__":
    main()
