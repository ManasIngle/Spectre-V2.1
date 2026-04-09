import os
import joblib
import pandas as pd
import yfinance as yf
from sklearn.metrics import classification_report, accuracy_score

MODEL_DIR = os.path.dirname(__file__)
MODEL_PATH = os.path.join(MODEL_DIR, "nifty_direction_model.pkl")

# We use the same feature extractor used in train_multitf.py
from train_multitf import add_features, FEATURE_COLUMNS, create_target

def test_on_sensex():
    print("==================================================")
    print(" Out-of-Sample Market Cross-Validation (SENSEX)")
    print("==================================================")
    
    # 1. Download Sensex Data (^BSESN) for the last 60 days (15min TF)
    print("Downloading Sensex (^BSESN) 15-minute data...")
    stock = yf.Ticker("^BSESN")
    df = stock.history(interval="15m", period="60d")
    
    if len(df) == 0:
        print("Failed to download Sensex data. Yahoo Finance might be rate limiting.")
        return
        
    print(f"Downloaded {len(df)} Sensex candles.")
    
    # 2. Extract the exact same technical features our Nifty model expects
    print("Computing 31 Technical Features...")
    df = add_features(df)
    
    # 3. Create the targets (using 15m threshold limits like Nifty: 0.12% move in 90 mins)
    df = create_target(df, forward_bars=6, threshold_pct=0.12)
    df.dropna(subset=FEATURE_COLUMNS + ['target'], inplace=True)
    
    X_sensex = df[FEATURE_COLUMNS].values
    y_sensex = df['target'].values + 1  # Map -1,0,1 to 0,1,2
    
    # 4. Load the NIFTY trained model
    if not os.path.exists(MODEL_PATH):
        print(f"Nifty model not found at {MODEL_PATH}")
        return
        
    model = joblib.load(MODEL_PATH)
    
    # 5. Predict and Benchmark
    print("Predicting Sensex movement using strictly NIFTY-learned logic...")
    y_pred = model.predict(X_sensex)
    
    accuracy = accuracy_score(y_sensex, y_pred)
    print(f"\n[RESULT] Nifty Model Accuracy on unknown SENSEX data: {accuracy*100:.2f}%\n")
    print(classification_report(y_sensex, y_pred, target_names=["DOWN", "SIDEWAYS", "UP"]))
    
    print("\nINTERPRETATION:")
    if accuracy > 0.40:
        print("Success! The model learned universal market mechanics (momentum, volatility)")
        print("rather than just memorizing the Nifty chart.")
    else:
        print("Failure. The model is overfitted to Nifty and cannot adapt to other indices.")

if __name__ == "__main__":
    test_on_sensex()
