import os
import joblib
import warnings
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.metrics import classification_report, accuracy_score

warnings.filterwarnings('ignore')
MODEL_DIR = os.path.dirname(__file__)
DATA_PATH = "/Users/manasingle/Edge/Market Dataset since 2015"

def load_and_merge_data():
    print("Loading NIFTY 50, NIFTY BANK, and India VIX minute data...")

    nifty = pd.read_csv(os.path.join(DATA_PATH, "NIFTY 50_minute.csv"))
    bank  = pd.read_csv(os.path.join(DATA_PATH, "NIFTY BANK_minute.csv"))
    vix_path = os.path.join(DATA_PATH, "INDIA VIX_minute.csv")

    # Parse Nifty
    nifty.rename(columns={'date':'Date','open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'}, inplace=True)
    nifty['Date'] = pd.to_datetime(nifty['Date'])
    nifty.set_index('Date', inplace=True)

    # Parse Bank Nifty
    bank.rename(columns={'date':'Date','open':'Bank_Open','high':'Bank_High','low':'Bank_Low','close':'Bank_Close'}, inplace=True)
    bank['Date'] = pd.to_datetime(bank['Date'])
    bank.set_index('Date', inplace=True)

    # Merge Nifty + BankNifty
    df = nifty.join(bank[['Bank_Open', 'Bank_High', 'Bank_Low', 'Bank_Close']], how='inner')
    df.sort_index(inplace=True)
    df.dropna(inplace=True)

    # Merge India VIX
    if os.path.exists(vix_path):
        vix = pd.read_csv(vix_path, parse_dates=['date'])
        vix.set_index('date', inplace=True)
        df = df.join(vix[['close']].rename(columns={'close': 'VIX_Close'}), how='left')
        df['VIX_Close'] = df['VIX_Close'].ffill()
        print(f"Merged successfully: {len(df):,} synced minutes (Nifty + BankNifty + VIX).")
    else:
        print(f"Merged successfully: {len(df):,} synced minutes. (VIX not found)")

    return df

def build_vectorized_rolling_candles(df):
    print("Executing Vectorized 5-Minute Rolling Aggregations...")
    # Nifty 50 Rolling
    df['Roll_Open'] = df['Open'].shift(4)
    df['Roll_High'] = df['High'].rolling(5).max()
    df['Roll_Low'] = df['Low'].rolling(5).min()
    df['Roll_Close'] = df['Close']
    df['Roll_Volume'] = df['Volume'].rolling(5).sum()
    
    # Bank Nifty Rolling
    df['Bank_Roll_Open'] = df['Bank_Open'].shift(4)
    df['Bank_Roll_High'] = df['Bank_High'].rolling(5).max()
    df['Bank_Roll_Low'] = df['Bank_Low'].rolling(5).min()
    df['Bank_Roll_Close'] = df['Bank_Close']
    
    df.dropna(inplace=True)
    
    # Swap standard columns so standard TA logic processes the 5m frame
    df['Open'] = df['Roll_Open']
    df['High'] = df['Roll_High']
    df['Low'] = df['Roll_Low']
    df['Close'] = df['Roll_Close']
    df['Volume'] = df['Roll_Volume']
    return df

def engineered_cross_features(df):
    from train_multitf import add_features, FEATURE_COLUMNS
    print("Calculating Vanilla 31 Technicals...")
    df = add_features(df)
    
    print("Calculating Custom Sectoral Features (BankNifty vs Nifty)...")
    # 1. BankNifty vs Nifty Spread (The Leading Indicator Edge)
    df['Bank_Return_5m'] = (df['Bank_Roll_Close'] - df['Bank_Roll_Open']) / df['Bank_Roll_Open'] * 100
    df['Nifty_Return_5m'] = (df['Close'] - df['Open']) / df['Open'] * 100
    df['feat_bank_spread'] = df['Bank_Return_5m'] - df['Nifty_Return_5m']
    
    # 2. BankNifty Volatility Proxy
    df['feat_bank_volatility'] = (df['Bank_Roll_High'] - df['Bank_Roll_Low']) / df['Bank_Roll_Close'] * 100
    
    CROSS_FEATURES = FEATURE_COLUMNS + ['feat_bank_spread', 'feat_bank_volatility']
    
    # Targets: 15 minutes forward (exactly 15 rows in minute data)
    # Asymmetric: DOWN requires 30% bigger move to reduce false bearish labels.
    forward_bars = 15
    threshold_pct = 0.08
    threshold_dn = threshold_pct * 1.3  # DOWN bar is higher (0.104%)

    close = df['Close']
    future_return = (close.shift(-forward_bars) - close) / close * 100
    df['target'] = 0
    df.loc[future_return > threshold_pct, 'target'] = 1
    df.loc[future_return < -threshold_dn, 'target'] = -1
    
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(subset=CROSS_FEATURES + ['target'], inplace=True)
    
    return df, CROSS_FEATURES

def train_and_backtest(df, feature_cols):
    X = df[feature_cols].values
    y = df['target'].values + 1 # Convert -1,0,1 to 0,1,2
    
    train_mask = df.index.year >= 2021
    test_mask = df.index.year < 2021
    
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[test_mask], y[test_mask]
    
    print(f"\nTraining on RECENT data (2021-Present): {len(X_train):,} samples")
    print(f"Testing on OLD data (Pre-2021): {len(X_test):,} samples")
    
    # -------------------------------------------------------------
    # THE FIX: Aggressive Sample Weights to kill the "Sideways" Trap
    # -------------------------------------------------------------
    class_counts = np.bincount(y_train)
    total = len(y_train)
    # We heavily penalize the model if it misses UP/DOWN moves
    weights = {i: total / (len(class_counts) * c) for i, c in enumerate(class_counts)}
    # Add a multiplier to explicitly force the model to be more aggressive on trends
    weights[0] *= 0.7  # Reduce DOWN importance — suppress false bearish (BUY PE win rate was 47.9%)
    weights[2] *= 2.0  # Double importance of UP (BUY CE win rate was 63.1%)
    weights[1] *= 0.5  # Halve the importance of SIDEWAYS
    
    sample_weights = np.array([weights[yi] for yi in y_train])
    
    base_model = XGBClassifier(
        n_estimators=300, 
        max_depth=8, 
        learning_rate=0.05, 
        subsample=0.8, 
        eval_metric='mlogloss',
        n_jobs=-1
    )
    
    print("Fitting Aggressive Cross-Asset Sectoral Model...")
    # NOTE: In professional workflows, we would use RandomizedSearchCV optimizing for 'f1_macro' here.
    # We fit with our heavily adjusted weights to make the model brave.
    base_model.fit(X_train, y_train, sample_weight=sample_weights, verbose=False)
    
    y_pred = base_model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    
    print(f"\n=============================================")
    print(f" AGGRESSIVE TREND AI ACCURACY: {acc*100:.2f}%")
    print(f"=============================================")
    print(classification_report(y_test, y_pred, target_names=["DOWN", "SIDEWAYS", "UP"]))
    
    # Save — versioned to preserve old model
    model_path = os.path.join(MODEL_DIR, "nifty_cross_asset_model-Rtr14April.pkl")
    joblib.dump(base_model, model_path)
    print(f"Aggressive Engine saved to {model_path}")

if __name__ == "__main__":
    df = load_and_merge_data()
    df = build_vectorized_rolling_candles(df)
    df, f_cols = engineered_cross_features(df)
    train_and_backtest(df, f_cols)
