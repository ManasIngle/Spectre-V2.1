import os
import joblib
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from xgboost import XGBClassifier
from sklearn.metrics import classification_report, accuracy_score
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit

warnings.filterwarnings('ignore')

MODEL_DIR = os.path.dirname(__file__)

def get_1m_data():
    print("Loading 10 Years of 1-minute data from Treasure Trove Dataset...")
    file_path = "/Users/manasingle/Edge/Market Dataset since 2015/NIFTY 50_minute.csv"
    vix_path  = "/Users/manasingle/Edge/Market Dataset since 2015/INDIA VIX_minute.csv"

    df = pd.read_csv(file_path)
    df.rename(columns={'date':'Date','open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'}, inplace=True)
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)
    df.sort_index(inplace=True)
    df.dropna(subset=['Close'], inplace=True)

    # Merge India VIX (1-minute)
    if os.path.exists(vix_path):
        vix = pd.read_csv(vix_path, parse_dates=['date'])
        vix.set_index('date', inplace=True)
        df = df.join(vix[['close']].rename(columns={'close': 'VIX_Close'}), how='left')
        df['VIX_Close'] = df['VIX_Close'].ffill()
        print(f"Successfully loaded {len(df):,} 1-minute candles with India VIX merged.")
    else:
        print(f"Successfully loaded {len(df):,} 1-minute candles. (VIX file not found)")

    return df

def build_rolling_5m_windows(df_1m):
    print("Constructing Custom Overlapping 5-Minute Rolling Windows...")
    
    # We create a new DataFrame where every row `i` represents the trailing 5 minutes
    rolling_df = pd.DataFrame(index=df_1m.index)
    
    # Needs at least 5 candles to form the first window
    open_prices = df_1m['Open'].values
    high_prices = df_1m['High'].values
    low_prices = df_1m['Low'].values
    close_prices = df_1m['Close'].values
    volumes = df_1m['Volume'].values
    
    r_open, r_high, r_low, r_close, r_vol = [], [], [], [], []
    
    # Start at the 5th minute
    for i in range(len(df_1m)):
        if i < 4:
            r_open.append(np.nan)
            r_high.append(np.nan)
            r_low.append(np.nan)
            r_close.append(np.nan)
            r_vol.append(np.nan)
        else:
            r_open.append(open_prices[i-4])
            r_high.append(np.max(high_prices[i-4:i+1]))
            r_low.append(np.min(low_prices[i-4:i+1]))
            r_close.append(close_prices[i]) # The current minute's close is the window's close
            r_vol.append(np.sum(volumes[i-4:i+1]))
            
    rolling_df['Open'] = r_open
    rolling_df['High'] = r_high
    rolling_df['Low'] = r_low
    rolling_df['Close'] = r_close
    rolling_df['Volume'] = r_vol
    
    rolling_df.dropna(inplace=True)
    print(f"Generated {len(rolling_df)} Rolling 5-Minute Structural Candles.")
    return rolling_df

def feature_engineering(df):
    from train_multitf import add_features, FEATURE_COLUMNS
    print("Calculating 31 Technical Features on rolling data...")
    df = add_features(df)
    
    # Target: 30 minutes into the future (30 rows at 1-min resolution)
    # Asymmetric thresholds: DOWN requires 30% bigger move to label.
    # Backtest insight: BUY PE win rate 47.9% vs BUY CE 63.1% — reduce false bearish labels.
    forward_bars = 30
    threshold_pct = 0.08  # Scalping threshold (UP)
    threshold_dn = threshold_pct * 1.3  # DOWN needs a bigger move (0.104%)

    close = df['Close']
    future_return = (close.shift(-forward_bars) - close) / close * 100
    df['target'] = 0
    df.loc[future_return > threshold_pct, 'target'] = 1
    df.loc[future_return < -threshold_dn, 'target'] = -1
    
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(subset=FEATURE_COLUMNS + ['target'], inplace=True)
    return df, FEATURE_COLUMNS

def train_model(df, feature_cols):
    X = df[feature_cols].values
    y = df['target'].values + 1 # Convert -1,0,1 to 0,1,2
    
    print("\nDataset Composition:")
    for cls, label in [(0, "DOWN"), (1, "SIDEWAYS"), (2, "UP")]:
        count = (y == cls).sum()
        print(f"  {label}: {count} ({count/len(y)*100:.1f}%)")
        
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    # Sample Weights (balanced, then reduce DOWN to suppress false bearish)
    # Backtest: BUY PE win rate 47.9% vs BUY CE 63.1% — be conservative on DOWN
    class_counts = np.bincount(y_train.astype(int))
    total = len(y_train)
    weights = {i: total / (len(class_counts) * c) if c > 0 else 1.0 for i, c in enumerate(class_counts)}
    weights[0] = max(weights[0] * 0.7, 0.5)  # DOWN: reduce weight → less false bearish
    sample_weights = np.array([weights[int(yi)] for yi in y_train])

    print("\nInitiating RandomizedSearchCV Hyperparameter Tuning on Rolling Data...")
    base_model = XGBClassifier(random_state=42, n_jobs=-1, eval_metric='mlogloss', use_label_encoder=False)
    
    param_dist = {
        'n_estimators': [200, 400],
        'max_depth': [6, 8, 10],
        'learning_rate': [0.01, 0.05],
        'subsample': [0.8, 1.0],
        'colsample_bytree': [0.8, 1.0]
    }
    
    random_search = RandomizedSearchCV(
        base_model, param_distributions=param_dist,
        n_iter=10, scoring='accuracy', cv=TimeSeriesSplit(n_splits=3), 
        random_state=42, n_jobs=-1, verbose=1
    )
    
    random_search.fit(X_train, y_train, sample_weight=sample_weights)
    print(f"\nBest Settings for Rolling Model: {random_search.best_params_}")
    
    model = random_search.best_estimator_
    
    # Final Fit
    model.fit(X_train, y_train, sample_weight=sample_weights, eval_set=[(X_test, y_test)], verbose=False)
    
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    
    print(f"\n=============================================")
    print(f" ROLLING MASTER ACCURACY: {accuracy*100:.2f}%")
    print(f"=============================================")
    print(classification_report(y_test, y_pred, target_names=["DOWN", "SIDEWAYS", "UP"]))
    
    # Save — versioned to preserve old model
    save_path = os.path.join(MODEL_DIR, "nifty_rolling_model-Rtr14April.pkl")
    joblib.dump(model, save_path)
    print(f"\nSaved Rolling Master AI to {save_path}")

if __name__ == "__main__":
    df_1m = get_1m_data()
    rolling_df = build_rolling_5m_windows(df_1m)
    # Re-attach VIX — the rolling window builder creates a new df dropping extra columns
    if 'VIX_Close' in df_1m.columns:
        rolling_df = rolling_df.join(df_1m[['VIX_Close']], how='left')
        rolling_df['VIX_Close'] = rolling_df['VIX_Close'].ffill()
    train_df, f_cols = feature_engineering(rolling_df)
    train_model(train_df, f_cols)
