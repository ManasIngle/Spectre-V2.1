# Spectre v1.2 — Model Retraining Plan

Based on backtest of 3,858 signals across 14 trading days (Mar 12 – Apr 13, 2026).

---

## Backtest Findings (the "why")

| Finding | Implication |
|---------|-------------|
| BUY CE optimal hold = **30 min, +9.53 pts, 63.1% win** | Bullish signals have real edge, let them run |
| BUY PE optimal hold = **8 min, +0.80 pts, 47.9% win** | Bearish signals only work as quick scalps |
| Conf 60%+ optimal = **7 min**, then decays hard | High confidence = right direction, wrong duration |
| Conf 55-60% = **+0.64 pts** (nearly dead) | This bucket adds noise, not signal |
| Conf 40-45% = **+7.72 pts at 29 min** | Medium confidence holds well |
| Overall accuracy 36.8% on 3-class | Sideways class is diluting edge |

---

## Phase 1: Prepare Training Data from Local Dataset

**Data source**: `/Users/manasingle/Edge/Market Dataset since 2015/`

This folder has 10+ years of OHLCV data (2015 – April 2026). Much richer than the ~60 days from Yahoo Finance.

**Available files we need:**

| File | Rows | Use |
|------|------|-----|
| `NIFTY 50_5minute.csv` | 207,881 | 5m scalp model + rolling model |
| `NIFTY 50_15minute.csv` | 69,308 | 15m swing model |
| `NIFTY 50_60minute.csv` | 19,412 | 1h trend model |
| `NIFTY 50_minute.csv` | 1,039,200 | Rolling master model |
| `NIFTY BANK_minute.csv` | 1,039,149 | Cross-asset model |
| `NIFTY BANK_5minute.csv` | 207,872 | Cross-asset model |
| `INDIA VIX_5minute.csv` | 207,825 | Optional: VIX feature |

**IMPORTANT — Column format mismatch:**

The local dataset uses lowercase columns:
```
date, open, high, low, close, volume
```

The training scripts expect capitalized columns:
```
Datetime, Open, High, Low, Close, Volume
```

**Step 1a**: Create a data prep script. Save as `ml_sidecar/models/prep_data.py`:

```python
"""
Prepare training data from the local 10-year market dataset.
Converts column names to match what train_multitf.py expects.
"""
import os
import shutil
import pandas as pd

DATASET_DIR = "/Users/manasingle/Edge/Market Dataset since 2015"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

FILES = {
    "nifty_5m.csv": "NIFTY 50_5minute.csv",
    "nifty_15m.csv": "NIFTY 50_15minute.csv",
    "nifty_1h.csv": "NIFTY 50_60minute.csv",
    "nifty_1m.csv": "NIFTY 50_minute.csv",
    "banknifty_1m.csv": "NIFTY BANK_minute.csv",
    "banknifty_5m.csv": "NIFTY BANK_5minute.csv",
    "vix_5m.csv": "INDIA VIX_5minute.csv",
}

for out_name, src_name in FILES.items():
    src_path = os.path.join(DATASET_DIR, src_name)
    out_path = os.path.join(DATA_DIR, out_name)
    
    if not os.path.exists(src_path):
        print(f"SKIP (not found): {src_name}")
        continue
    
    print(f"Processing {src_name} -> {out_name}...", end=" ")
    df = pd.read_csv(src_path)
    
    # Rename columns: date->Datetime, open->Open, etc.
    df.rename(columns={
        "date": "Datetime",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }, inplace=True)
    
    # Set Datetime as index (what train_multitf load_data expects)
    df["Datetime"] = pd.to_datetime(df["Datetime"])
    df.set_index("Datetime", inplace=True)
    df.sort_index(inplace=True)
    
    # Drop rows with zero/null close
    df = df[df["Close"] > 0]
    
    df.to_csv(out_path)
    print(f"{len(df):,} rows")

print("\nDone. Data ready in:", DATA_DIR)
```

**Run it:**
```bash
cd /Users/manasingle/Edge/Spectre-1.2\ stable/spectre-go/ml_sidecar/models
python prep_data.py
```

---

## Phase 2: Modify Training Script

**File to edit**: `ml_sidecar/models/train_multitf.py`

### Change 1: Asymmetric Target Thresholds

Current target treats UP and DOWN symmetrically. But backtest shows bearish signals are weaker. Use tighter threshold for DOWN to reduce false bearish signals.

Replace `create_target()` function:

```python
def create_target(df: pd.DataFrame, forward_bars: int, threshold_pct: float) -> pd.DataFrame:
    """Create direction target with asymmetric thresholds.
    
    Bearish signals have weaker edge in backtesting, so we use a higher
    threshold for DOWN to reduce false bearish calls.
    """
    close = df['Close']
    future_return = (close.shift(-forward_bars) - close) / close * 100
    
    up_threshold = threshold_pct          # e.g. 0.08%
    down_threshold = threshold_pct * 1.3  # 30% higher bar for DOWN calls
    
    df['target'] = 0  # SIDEWAYS
    df.loc[future_return > up_threshold, 'target'] = 1     # UP
    df.loc[future_return < -down_threshold, 'target'] = -1  # DOWN
    return df
```

### Change 2: Asymmetric Class Weights

The model should be more confident before calling DOWN. Increase DOWN class weight so it only fires on stronger bearish setups.

In `train_xgboost()`, replace the class weights section:

```python
    # Asymmetric class weights: make DOWN harder to predict (requires stronger signal)
    class_counts = np.bincount(y_train.astype(int))
    total = len(y_train)
    n_classes = len(class_counts)
    base_weights = {i: total / (n_classes * c) if c > 0 else 1.0
                    for i, c in enumerate(class_counts)}
    
    # Boost DOWN weight by 1.5x — model must be more sure before predicting DOWN
    base_weights[0] = base_weights[0] * 1.5  # DOWN class
    # Reduce SIDEWAYS weight — we care less about sideways accuracy
    base_weights[1] = base_weights[1] * 0.7  # SIDEWAYS class
    
    sample_weights = np.array([base_weights[int(yi)] for yi in y_train])
```

### Change 3: Add Directional Momentum Features

The backtest shows BUY CE signals have momentum (profitable at 30 min = trend continuation). Add features that capture this.

In `add_features()`, add these before the `return df`:

```python
    # Consecutive candle direction (momentum streak)
    df['feat_consec_up'] = (close > close.shift(1)).rolling(5).sum()
    df['feat_consec_down'] = (close < close.shift(1)).rolling(5).sum()
    
    # Price position relative to session range (intraday trend strength)
    session_high = high.rolling(78).max()  # ~6.5h of 5m bars
    session_low = low.rolling(78).min()
    session_range = session_high - session_low
    df['feat_session_position'] = np.where(session_range > 0,
        (close - session_low) / session_range, 0.5)
    
    # Short-term vs medium-term momentum divergence
    df['feat_momentum_divergence'] = df['feat_roc_6'] - df['feat_roc_12']
```

Also add these to `FEATURE_COLUMNS` list:

```python
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
    # NEW: momentum features from backtest insights
    'feat_consec_up', 'feat_consec_down',
    'feat_session_position', 'feat_momentum_divergence',
]
```

### Change 4: Tune XGBoost Hyperparameters

Add more regularization and tighter depth to prevent overfitting:

```python
    param_dist = {
        'n_estimators': [200, 300, 400, 500],
        'max_depth': [3, 4, 5, 6],           # reduced max from 10 to 6
        'learning_rate': [0.01, 0.03, 0.05, 0.1],
        'subsample': [0.6, 0.7, 0.8],
        'colsample_bytree': [0.5, 0.6, 0.7, 0.8],
        'reg_alpha': [0.1, 0.5, 1.0, 2.0],   # more L1 regularization
        'reg_lambda': [1.0, 3.0, 5.0, 10.0],  # more L2 regularization
        'min_child_weight': [3, 5, 7, 10],    # NEW: prevent fitting noise
        'gamma': [0, 0.1, 0.3, 0.5],          # NEW: min split loss
    }
```

Also increase search iterations and folds:

```python
    random_search = RandomizedSearchCV(
        base_model, param_distributions=param_dist,
        n_iter=30, scoring='accuracy', cv=TimeSeriesSplit(n_splits=5),
        random_state=42, n_jobs=-1, verbose=1
    )
```

---

## Phase 3: Retrain the Rolling Model

**File**: `ml_sidecar/models/train_rolling_master.py`

Apply the same changes:
1. Asymmetric thresholds in target creation
2. Add the 4 new features
3. Update FEATURE_COLUMNS to include them

This model uses `data/nifty_1m.csv` (1M+ rows, prepared in Phase 1 from the local 10-year dataset).

```bash
python train_rolling_master.py
```

---

## Phase 4: Retrain Cross-Asset Model

**File**: `ml_sidecar/models/train_cross_asset.py`

This model uses BankNifty + Nifty data. Apply:
1. Asymmetric thresholds
2. Add the 4 new momentum features (now 37 total)
3. Update feature columns
4. Update data path to use `data/banknifty_1m.csv` and `data/nifty_1m.csv` (prepared in Phase 1)

```bash
python train_cross_asset.py
```

---

## Phase 5: Run Training

Execute in order:

```bash
cd /Users/manasingle/Edge/Spectre-1.2\ stable/spectre-go/ml_sidecar/models

# Step 1: Prepare data from local 10-year dataset
python prep_data.py

# Step 2: Train all XGBoost models (skip LSTM for now — XGBoost is the primary)
python train_multitf.py --xgb-only

# Step 3: Train rolling model (uses 1M+ minute bars)
python train_rolling_master.py

# Step 4: Train cross-asset model
python train_cross_asset.py
```

After each training, check:
- Accuracy should be > 40% (up from 36.8%)
- DOWN class precision should be > 35%
- UP class recall should be > 40%

**Note**: With 200K+ 5m rows instead of 3,400 — this will take longer to train but produce much more robust models.

---

## Phase 6: Update Sidecar Feature Extraction

**File**: `ml_sidecar/sidecar.py` — function `_extract_features()`

Add the 4 new features to match training. Find the section where features are built and add:

```python
    # Consecutive direction features
    consec_up = sum(1 for i in range(1, min(6, len(df))) if df.Close.iloc[-i] > df.Close.iloc[-i-1])
    consec_down = sum(1 for i in range(1, min(6, len(df))) if df.Close.iloc[-i] < df.Close.iloc[-i-1])
    
    # Session position
    session_high = df.High.rolling(78, min_periods=1).max().iloc[-1]
    session_low = df.Low.rolling(78, min_periods=1).min().iloc[-1]
    session_range = session_high - session_low
    session_pos = (df.Close.iloc[-1] - session_low) / session_range if session_range > 0 else 0.5
    
    # Momentum divergence
    roc_6 = (df.Close.iloc[-1] - df.Close.iloc[-7]) / df.Close.iloc[-7] * 100 if len(df) > 7 else 0
    roc_12 = (df.Close.iloc[-1] - df.Close.iloc[-13]) / df.Close.iloc[-13] * 100 if len(df) > 13 else 0
    momentum_div = roc_6 - roc_12
```

Then add these values to the feature vector in the **exact same order** as `FEATURE_COLUMNS` in training.

**CRITICAL**: The feature order in `_extract_features()` MUST match `FEATURE_COLUMNS` in training exactly. After training, open the generated `model_metadata_5m.json` and verify the `feature_columns` array matches what the sidecar builds.

---

## Phase 7: Update Go Backend Hold Times

**File**: `spectre-go/services/trade_signals.go`

Replace the dynamic hold time calculation (the `baseMinutes` block around line 173) with backtest-optimized values:

```go
    // Backtest-optimized hold times (from optimal_hold.py analysis)
    baseMinutes := 25.0 // default
    
    if pred == "DOWN" {
        // BUY PE: quick scalp only (backtest optimal = 8 min)
        baseMinutes = 8.0
        if conf > 60 {
            baseMinutes = 5.0 // high conf DOWN = even faster exit
        }
    } else if pred == "UP" {
        // BUY CE: let it run (backtest optimal = 25-30 min)
        if conf > 60 {
            baseMinutes = 8.0  // high conf = scalp (decays after 7 min)
        } else if conf > 45 {
            baseMinutes = 25.0 // moderate conf = full hold
        } else {
            baseMinutes = 15.0 // low conf = medium hold
        }
    } else {
        baseMinutes = 10.0 // SIDEWAYS / NO TRADE
    }
```

Also remove or simplify the ATR adjustment that follows (the `if atrPct > 0.6` block) — the backtest already accounts for volatility regimes in the optimal hold times.

---

## Phase 8: Test and Deploy

1. **Test locally**: Run sidecar with new models
   ```bash
   cd ml_sidecar && pip install -r requirements.txt && python sidecar.py
   # In another terminal: curl http://localhost:8240/predict | python -m json.tool
   ```

2. **Verify feature count matches**: The response should have valid probs (not errors). Check that `probs` has 3 values that sum to ~1.0.

3. **Push and deploy**:
   ```bash
   git add ml_sidecar/models/*.pkl ml_sidecar/models/model_metadata*.json ml_sidecar/sidecar.py services/trade_signals.go
   git commit -m "Retrain models with asymmetric targets and optimized hold times"
   git push origin main
   ```

4. **Delete old CSV on server** (redeploy creates fresh container, so CSV resets automatically unless using persistent volume).

---

## Expected Improvements

| Metric | Before | Target |
|--------|--------|--------|
| Overall accuracy | 36.8% | 42-48% |
| BUY PE win rate | 33% | 38-42% (fewer but better PE calls) |
| BUY CE win rate | 34% | 40-45% |
| False DOWN rate | High | Reduced (asymmetric threshold) |
| 60%+ conf P&L after 7 min | +4.72 then decays | Same or better (hold time matches) |
| Training data | ~3,400 5m rows (60 days) | ~207,000 5m rows (10 years) |

---

## Summary of Files to Modify

| File | Change |
|------|--------|
| `ml_sidecar/models/prep_data.py` | NEW — converts local dataset columns to training format |
| `ml_sidecar/models/train_multitf.py` | Asymmetric targets, class weights, new features, tuning |
| `ml_sidecar/models/train_rolling_master.py` | Same changes as above |
| `ml_sidecar/models/train_cross_asset.py` | Same changes as above |
| `ml_sidecar/sidecar.py` | Add 4 new features to `_extract_features()` |
| `services/trade_signals.go` | Backtest-optimized hold times |

## Execution Order

1. Create `prep_data.py` and run it (converts local dataset)
2. Edit `train_multitf.py` (all 4 changes)
3. Edit `train_rolling_master.py` (same changes)
4. Edit `train_cross_asset.py` (same changes)
5. Run all training scripts
6. Edit `sidecar.py` (add 4 new features to inference)
7. Test locally (`curl /predict`)
8. Edit `trade_signals.go` (hold times)
9. Commit, push, deploy
