"""
Train XGBoost model for Nifty 30-minute direction prediction.
Outputs: nifty_direction_model.pkl + feature_columns.json
"""
import os
import json
import numpy as np
import pandas as pd
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix
from feature_builder import build_features, get_feature_columns

MODEL_DIR = os.path.dirname(__file__)


def train():
    print("=" * 60)
    print("NiftyTrader Pro — XGBoost Model Training")
    print("=" * 60)

    # 1. Build features
    df, feature_cols = build_features()

    X = df[feature_cols].values
    y = df['target'].values  # -1, 0, 1

    # Map target to 0,1,2 for XGBoost
    # -1 → 0 (DOWN), 0 → 1 (SIDEWAYS), 1 → 2 (UP)
    y_mapped = y + 1

    print(f"\nDataset: {len(X)} samples, {len(feature_cols)} features")
    print(f"Class distribution:")
    for cls, label in [(0, "DOWN"), (1, "SIDEWAYS"), (2, "UP")]:
        count = (y_mapped == cls).sum()
        print(f"  {label}: {count} ({count/len(y_mapped)*100:.1f}%)")

    # 2. Chronological train/test split (80/20)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y_mapped[:split_idx], y_mapped[split_idx:]

    print(f"\nTrain: {len(X_train)}, Test: {len(X_test)}")

    # 3. Handle class imbalance with sample weights
    class_counts = np.bincount(y_train.astype(int))
    total = len(y_train)
    n_classes = len(class_counts)
    class_weights = {i: total / (n_classes * c) if c > 0 else 1.0
                     for i, c in enumerate(class_counts)}
    sample_weights = np.array([class_weights[int(y)] for y in y_train])

    print(f"Class weights: {class_weights}")

    # 4. Train XGBoost
    print("\nTraining XGBoost...")
    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=-1,
        eval_metric='mlogloss',
        use_label_encoder=False,
    )

    model.fit(
        X_train, y_train,
        sample_weight=sample_weights,
        eval_set=[(X_test, y_test)],
        verbose=50,
    )

    # 5. Evaluate
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)

    print("\n" + "=" * 40)
    print("EVALUATION RESULTS")
    print("=" * 40)

    accuracy = accuracy_score(y_test, y_pred)
    print(f"\nAccuracy: {accuracy:.4f}")

    labels = ["DOWN", "SIDEWAYS", "UP"]
    print(f"\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=labels))

    print(f"Confusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    print(pd.DataFrame(cm, index=labels, columns=labels).to_string())

    # 6. Feature importance
    importances = model.feature_importances_
    feat_imp = sorted(zip(feature_cols, importances), key=lambda x: x[1], reverse=True)
    print(f"\nTop 10 Features:")
    for name, imp in feat_imp[:10]:
        print(f"  {name}: {imp:.4f}")

    # 7. Save model and metadata
    model_path = os.path.join(MODEL_DIR, "nifty_direction_model.pkl")
    joblib.dump(model, model_path)
    print(f"\nModel saved: {model_path}")

    # Save feature columns
    meta = {
        "feature_columns": feature_cols,
        "class_mapping": {0: "DOWN", 1: "SIDEWAYS", 2: "UP"},
        "target_mapping": {"DOWN": -1, "SIDEWAYS": 0, "UP": 1},
        "accuracy": round(accuracy, 4),
        "n_training_samples": len(X_train),
        "n_test_samples": len(X_test),
        "threshold_pct": 0.15,
        "forward_bars": 6,
    }
    meta_path = os.path.join(MODEL_DIR, "model_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata saved: {meta_path}")

    print("\n" + "=" * 60)
    print("Training complete!")
    print("=" * 60)

    return model, accuracy


if __name__ == "__main__":
    train()
