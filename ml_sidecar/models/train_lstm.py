"""
Train LSTM model for Nifty direction prediction.
Uses raw OHLCV sequences (windows of N candles) to learn temporal patterns.
Ensemble with XGBoost for final direction voting.

Outputs: nifty_lstm_model.keras + lstm_scaler.pkl + lstm_metadata.json
"""
import os
import sys
import io
import json
import numpy as np
import pandas as pd
import joblib

# Fix Windows encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Suppress TF warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

MODEL_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(MODEL_DIR, "data")

# ─── Config ──────────────────────────────────────────────────────────────────
SEQUENCE_LENGTH = 30    # Look back 30 candles
FORWARD_BARS = 6        # Predict 6 bars ahead (same as XGBoost)
THRESHOLD_PCT = 0.15    # Same threshold as XGBoost
EPOCHS = 50
BATCH_SIZE = 32


def load_and_prepare_data():
    """Load Nifty hourly data and prepare sequences."""
    # Try hourly first (more data), fall back to 5m
    hourly_path = os.path.join(DATA_DIR, "nifty_1h.csv")
    fivemin_path = os.path.join(DATA_DIR, "nifty_5m.csv")

    if os.path.exists(hourly_path):
        df = pd.read_csv(hourly_path)
        print(f"Loaded hourly data: {len(df)} rows")
    elif os.path.exists(fivemin_path):
        df = pd.read_csv(fivemin_path)
        print(f"Loaded 5-min data: {len(df)} rows")
    else:
        raise FileNotFoundError("No Nifty data found. Run data_downloader.py first.")

    # Ensure columns exist
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col not in df.columns:
            raise ValueError(f"Missing column: {col}")

    df = df.dropna(subset=['Open', 'High', 'Low', 'Close', 'Volume'])
    df = df.reset_index(drop=True)

    return df


def create_features(df):
    """Create normalized features for LSTM input."""
    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values
    opn = df['Open'].values
    volume = df['Volume'].values

    features = np.column_stack([
        # 1. Returns (price changes)
        np.concatenate([[0], np.diff(close) / close[:-1] * 100]),
        # 2. High-Low range %
        (high - low) / close * 100,
        # 3. Open-Close body %
        (close - opn) / close * 100,
        # 4. Upper shadow %
        (high - np.maximum(close, opn)) / close * 100,
        # 5. Lower shadow %
        (np.minimum(close, opn) - low) / close * 100,
        # 6. Volume change ratio
        np.concatenate([[1], volume[1:] / np.maximum(volume[:-1], 1)]),
        # 7. Close position within range (0=low, 1=high)
        np.where(high - low > 0, (close - low) / (high - low), 0.5),
        # 8. Gap from previous close
        np.concatenate([[0], (opn[1:] - close[:-1]) / close[:-1] * 100]),
    ])

    return features


def create_sequences(features, close_prices, seq_len, forward_bars, threshold):
    """Create input sequences (X) and target labels (y)."""
    X, y = [], []

    for i in range(seq_len, len(features) - forward_bars):
        # Input: seq_len candles of features
        X.append(features[i - seq_len:i])

        # Target: direction of close price forward_bars ahead
        current = close_prices[i]
        future = close_prices[i + forward_bars]
        pct_change = (future - current) / current * 100

        if pct_change > threshold:
            y.append(2)   # UP
        elif pct_change < -threshold:
            y.append(0)   # DOWN
        else:
            y.append(1)   # SIDEWAYS

    return np.array(X), np.array(y)


def build_lstm_model(input_shape, num_classes=3):
    """Build a 2-layer LSTM model with dropout."""
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization

    model = Sequential([
        LSTM(64, return_sequences=True, input_shape=input_shape),
        Dropout(0.3),
        BatchNormalization(),

        LSTM(32, return_sequences=False),
        Dropout(0.3),
        BatchNormalization(),

        Dense(32, activation='relu'),
        Dropout(0.2),

        Dense(num_classes, activation='softmax'),
    ])

    model.compile(
        optimizer='adam',
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy'],
    )

    return model


def train():
    print("=" * 60)
    print("NiftyTrader Pro — LSTM Model Training")
    print("=" * 60)

    # 1. Load data
    df = load_and_prepare_data()

    # 2. Create features
    print("\nCreating features...")
    features = create_features(df)
    close_prices = df['Close'].values
    print(f"Feature matrix: {features.shape}")

    # 3. Scale features
    from sklearn.preprocessing import RobustScaler
    scaler = RobustScaler()
    features_scaled = scaler.fit_transform(features)
    print(f"Features scaled with RobustScaler")

    # 4. Create sequences
    print(f"\nCreating sequences (window={SEQUENCE_LENGTH}, forward={FORWARD_BARS}, threshold={THRESHOLD_PCT}%)...")
    X, y = create_sequences(features_scaled, close_prices, SEQUENCE_LENGTH, FORWARD_BARS, THRESHOLD_PCT)
    print(f"Total sequences: {len(X)}")
    print(f"Input shape: {X.shape}  (samples, timesteps, features)")

    # Class distribution
    for cls, label in [(0, "DOWN"), (1, "SIDEWAYS"), (2, "UP")]:
        count = (y == cls).sum()
        print(f"  {label}: {count} ({count/len(y)*100:.1f}%)")

    # 5. Chronological split (80/20)
    split = int(len(X) * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]
    print(f"\nTrain: {len(X_train)}, Test: {len(X_test)}")

    # 6. Handle class imbalance with class weights
    from sklearn.utils.class_weight import compute_class_weight
    classes = np.unique(y_train)
    weights = compute_class_weight('balanced', classes=classes, y=y_train)
    class_weight_dict = dict(zip(classes.astype(int), weights))
    print(f"Class weights: {class_weight_dict}")

    # 7. Build model
    print("\nBuilding LSTM model...")
    model = build_lstm_model(input_shape=(X_train.shape[1], X_train.shape[2]))
    model.summary()

    # 8. Train with early stopping
    from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

    callbacks = [
        EarlyStopping(monitor='val_loss', patience=8, restore_best_weights=True),
        ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=4, min_lr=1e-6),
    ]

    print(f"\nTraining for up to {EPOCHS} epochs...")
    history = model.fit(
        X_train, y_train,
        validation_data=(X_test, y_test),
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        class_weight=class_weight_dict,
        callbacks=callbacks,
        verbose=1,
    )

    # 9. Evaluate
    from sklearn.metrics import classification_report, accuracy_score, confusion_matrix

    y_pred_prob = model.predict(X_test)
    y_pred = np.argmax(y_pred_prob, axis=1)

    accuracy = accuracy_score(y_test, y_pred)

    print("\n" + "=" * 40)
    print("LSTM EVALUATION RESULTS")
    print("=" * 40)
    print(f"\nAccuracy: {accuracy:.4f}")

    labels = ["DOWN", "SIDEWAYS", "UP"]
    print(f"\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=labels))

    print(f"Confusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    print(pd.DataFrame(cm, index=labels, columns=labels).to_string())

    # 10. Save model, scaler, metadata
    model_path = os.path.join(MODEL_DIR, "nifty_lstm_model.keras")
    model.save(model_path)
    print(f"\nLSTM model saved: {model_path}")

    scaler_path = os.path.join(MODEL_DIR, "lstm_scaler.pkl")
    joblib.dump(scaler, scaler_path)
    print(f"Scaler saved: {scaler_path}")

    meta = {
        "sequence_length": SEQUENCE_LENGTH,
        "n_features": X_train.shape[2],
        "feature_names": [
            "return_pct", "hl_range_pct", "oc_body_pct", "upper_shadow_pct",
            "lower_shadow_pct", "volume_change_ratio", "close_position", "gap_pct"
        ],
        "class_mapping": {0: "DOWN", 1: "SIDEWAYS", 2: "UP"},
        "accuracy": round(float(accuracy), 4),
        "n_training_samples": len(X_train),
        "n_test_samples": len(X_test),
        "epochs_trained": len(history.history['loss']),
        "best_val_loss": round(float(min(history.history['val_loss'])), 4),
        "threshold_pct": THRESHOLD_PCT,
        "forward_bars": FORWARD_BARS,
    }
    meta_path = os.path.join(MODEL_DIR, "lstm_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata saved: {meta_path}")

    print("\n" + "=" * 60)
    print("LSTM Training complete!")
    print("=" * 60)

    return model, accuracy


if __name__ == "__main__":
    train()
