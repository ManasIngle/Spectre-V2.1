"""
Feature Builder for ML Model Training
Extracts ~35 features from Nifty OHLCV data for model training.
Supports both hourly (3y coverage) and 5m (recent 60d) data.
"""
import pandas as pd
import numpy as np
import os
import sys
import io
from ta.trend import ADXIndicator, MACD, EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import VolumeWeightedAveragePrice

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Nifty weight for top contributors (approximate)
EQUITY_WEIGHTS = {
    "HDFCBANK": 0.13, "RELIANCE": 0.10, "ICICIBANK": 0.08, "INFY": 0.07,
    "TCS": 0.04, "BHARTIARTL": 0.04, "ITC": 0.04, "LT": 0.03,
    "SBIN": 0.03, "BAJFINANCE": 0.02,
}


def load_nifty_data(use_hourly=True):
    """
    Load Nifty price data.
    Priority: hourly (long history) > 5m (short but granular)
    """
    if use_hourly:
        path = os.path.join(DATA_DIR, "nifty_1h.csv")
        if os.path.exists(path):
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            df.dropna(subset=['Close'], inplace=True)
            print(f"Loaded Nifty HOURLY: {len(df)} rows")
            return df, "1h"

    path = os.path.join(DATA_DIR, "nifty_5m.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.dropna(subset=['Close'], inplace=True)
        print(f"Loaded Nifty 5M: {len(df)} rows")
        return df, "5m"

    # Fallback to daily
    path = os.path.join(DATA_DIR, "nifty_daily.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.dropna(subset=['Close'], inplace=True)
        print(f"Loaded Nifty DAILY: {len(df)} rows")
        return df, "1d"

    raise FileNotFoundError("No Nifty data found! Run data_downloader.py first.")


def load_contributors(interval="1h"):
    """Load top contributor stock data at matching interval."""
    suffix = "_1h.csv" if interval in ("1h",) else "_daily.csv"
    contributors = {}
    for name in EQUITY_WEIGHTS.keys():
        path = os.path.join(DATA_DIR, f"{name}{suffix}")
        if os.path.exists(path):
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            df.dropna(subset=['Close'], inplace=True)
            contributors[name] = df
    # If no hourly data, fall back to daily
    if not contributors and suffix == "_1h.csv":
        return load_contributors(interval="1d")
    print(f"Loaded {len(contributors)} contributors ({suffix})")
    return contributors


def add_indicator_features(df):
    """Add all technical indicator features to the DataFrame."""
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
    macd_ind = MACD(close)
    df['feat_macd_hist'] = macd_ind.macd_diff()

    # EMA 9/21 spread (as % of price)
    ema9 = EMAIndicator(close, window=9).ema_indicator()
    ema21 = EMAIndicator(close, window=21).ema_indicator()
    df['feat_ema_spread'] = ((ema9 - ema21) / close) * 100

    # VWAP deviation — use volume-weighted moving average (works on all intervals)
    vw_avg = (close * volume).rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)
    df['feat_vwap_dev'] = ((close - vw_avg) / close * 100).fillna(0)

    # Supertrend direction (simplified)
    atr = AverageTrueRange(high, low, close, window=10).average_true_range()
    hl2 = (high + low) / 2
    upper = hl2 + 2 * atr
    lower = hl2 - 2 * atr
    df['feat_st_direction'] = np.where(close > upper.shift(1), 1,
                              np.where(close < lower.shift(1), -1, 0))

    return df


def add_volume_features(df):
    """Volume-based features."""
    vol = df['Volume']
    avg20 = vol.rolling(20).mean()
    df['feat_rel_vol'] = np.where(avg20 > 0, vol / avg20, 1)
    avg5 = vol.rolling(5).mean()
    df['feat_vol_trend'] = np.where(avg20 > 0, avg5 / avg20, 1)
    return df


def add_momentum_features(df):
    """Momentum and rate-of-change features."""
    close = df['Close']

    # Rate of change (6-bar = ~6 hours for 1h data, 30 min for 5m)
    df['feat_roc_6'] = close.pct_change(6) * 100
    df['feat_roc_12'] = close.pct_change(12) * 100

    # Bollinger Band position (0 = lower band, 1 = upper band)
    bb = BollingerBands(close, window=20, window_dev=2)
    bb_upper = bb.bollinger_hband()
    bb_lower = bb.bollinger_lband()
    bb_range = bb_upper - bb_lower
    df['feat_bb_pos'] = np.where(bb_range > 0, (close - bb_lower) / bb_range, 0.5)

    # ATR-normalized move
    atr = AverageTrueRange(df['High'], df['Low'], close, window=14).average_true_range()
    df['feat_atr_move'] = np.where(atr > 0, (close - close.shift(1)) / atr, 0)

    # Lagged returns
    df['feat_ret_1'] = close.pct_change(1) * 100
    df['feat_ret_2'] = close.pct_change(2) * 100
    df['feat_ret_3'] = close.pct_change(3) * 100

    return df


def add_higher_tf_features(df):
    """Higher timeframe context (derived from current timeframe bars)."""
    close = df['Close']

    # Slow RSI (approximates higher TF)
    df['feat_slow_rsi'] = RSIIndicator(close, window=42).rsi()

    # Slow MACD (approximates higher TF)
    try:
        macd_slow = MACD(close, window_slow=52, window_fast=24, window_sign=18)
        df['feat_slow_macd_hist'] = macd_slow.macd_diff()
    except Exception:
        df['feat_slow_macd_hist'] = 0

    # Slow Supertrend direction
    atr_slow = AverageTrueRange(df['High'], df['Low'], close, window=30).average_true_range()
    hl2 = (df['High'] + df['Low']) / 2
    upper = hl2 + 2 * atr_slow
    lower = hl2 - 2 * atr_slow
    df['feat_slow_st_dir'] = np.where(close > upper.shift(1), 1,
                             np.where(close < lower.shift(1), -1, 0))

    return df


def add_equity_contribution_features(df, contributors):
    """Measure how top Nifty heavyweights are contributing to movement."""
    weighted_returns = pd.Series(0.0, index=df.index)
    advancing_count = pd.Series(0.0, index=df.index)
    total_stocks = 0

    for name, stock_df in contributors.items():
        if name not in EQUITY_WEIGHTS or stock_df.empty:
            continue
        stock_close = stock_df['Close'].reindex(df.index, method='ffill')
        stock_ret = stock_close.pct_change(6) * 100  # 6-bar return

        w = EQUITY_WEIGHTS.get(name, 0.02)
        weighted_returns = weighted_returns + stock_ret.fillna(0) * w
        advancing_count = advancing_count + (stock_ret > 0).astype(float)
        total_stocks += 1

    df['feat_equity_weighted_ret'] = weighted_returns
    df['feat_equity_advance_pct'] = (advancing_count / max(total_stocks, 1)) * 100
    df['feat_equity_momentum'] = weighted_returns.rolling(3).mean()

    return df


def add_time_features(df):
    """Time-based features."""
    df['feat_hour'] = df.index.hour
    df['feat_minutes_since_open'] = (df.index.hour - 9) * 60 + df.index.minute - 15
    df['feat_day_of_week'] = df.index.dayofweek
    return df


def add_regime_features(df):
    """Market regime features."""
    close = df['Close']
    atr = AverageTrueRange(df['High'], df['Low'], close, window=20).average_true_range()
    df['feat_volatility'] = np.where(close > 0, (atr / close) * 100, 0)
    df['feat_trend_strength'] = df['feat_adx'].fillna(0)
    return df


def add_futures_proxy(df):
    """Futures premium proxy (approximated from price pattern)."""
    close = df['Close']
    ema50 = close.ewm(span=50).mean()
    df['feat_futures_premium_proxy'] = np.where(close > 0, ((close - ema50) / close) * 100, 0)
    df['feat_premium_change_rate'] = df['feat_futures_premium_proxy'].diff(6)
    return df


def create_target(df, forward_bars=6, threshold_pct=0.15):
    """
    Create the target: direction in next N bars.
    +1 = UP (price rises > threshold %)
    -1 = DOWN (price falls > threshold %)
     0 = SIDEWAYS (within threshold)
    """
    close = df['Close']
    future_return = (close.shift(-forward_bars) - close) / close * 100

    df['target'] = 0
    df.loc[future_return > threshold_pct, 'target'] = 1
    df.loc[future_return < -threshold_pct, 'target'] = -1
    df['future_return'] = future_return

    return df


def get_feature_columns():
    """Return the ordered list of feature column names."""
    return [
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


def build_features(df=None, contributors=None, use_hourly=True):
    """
    Main feature building pipeline.
    If df is None, loads from CSV files.
    """
    interval = "1h"
    if df is None:
        df, interval = load_nifty_data(use_hourly=use_hourly)
    if contributors is None:
        contributors = load_contributors(interval=interval)

    print(f"Building features on {len(df)} rows ({interval} data)...")

    df = add_indicator_features(df)
    df = add_volume_features(df)
    df = add_momentum_features(df)
    df = add_higher_tf_features(df)
    df = add_equity_contribution_features(df, contributors)
    df = add_time_features(df)
    df = add_regime_features(df)
    df = add_futures_proxy(df)
    df = create_target(df, forward_bars=6, threshold_pct=0.15)

    feature_cols = get_feature_columns()

    # Drop NaN rows
    before = len(df)
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(subset=feature_cols + ['target'], inplace=True)
    print(f"Feature building complete: {len(df)} usable rows (dropped {before - len(df)})")

    return df, feature_cols


if __name__ == "__main__":
    df, cols = build_features()
    print(f"\nFeatures ({len(cols)}):")
    for c in cols:
        print(f"  {c}")
    print(f"\nTarget distribution:")
    vc = df['target'].value_counts()
    for k, v in vc.items():
        label = {-1: "DOWN", 0: "SIDEWAYS", 1: "UP"}.get(k, str(k))
        print(f"  {label}: {v} ({v/len(df)*100:.1f}%)")

    # Save processed data
    output_path = os.path.join(DATA_DIR, "features.csv")
    df.to_csv(output_path)
    print(f"\nSaved features to: {output_path}")
