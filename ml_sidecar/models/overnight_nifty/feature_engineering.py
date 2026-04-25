"""
Overnight Nifty LSTM — feature engineering.

Critical principle: every feature for predicting day T's Nifty close must be
KNOWN by ~03:30 IST on day T (i.e. after US close on day T-1 and during Asia
open on day T). Concretely:

  - Nifty OHLCV: lag by 1 (we use day T-1's bars to predict day T)
  - US/EU markets: same-calendar-day close from day T-1 (their close lands ~02:00 IST on T)
  - Asia (Nikkei) open is ~05:30 IST so its close from T-1 is fine; for cues
    on day T we only have the Asia OPEN before NSE opens. We approximate with
    Nikkei close from T-1 (already lagged with `shift(1)` because the close on
    Nikkei lands during NSE hours on T-1, so it's known by overnight on T).

Feature groups:
  * Cross-asset overnight returns (sp500, nasdaq, dow, dxy, usdinr, brent, gold, nikkei, us10y, vix)
  * Nifty technicals (lagged): RSI(14), 5d/20d returns, ATR-normalised range
  * Calendar: day-of-week, month
  * Regime: VIX level/change, USD/INR change

Targets (built for next-day close on top of the lagged feature row):
  * y_logret  — log return from prev_close to next_close (regression)
  * y_dir     — UP / DOWN / FLAT (3 classes, threshold ±0.15%)
  * y_mag     — magnitude bucket (4 classes: <0.25, 0.25-0.75, 0.75-1.5, >1.5 abs %)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DIR_THRESHOLD = 0.0030      # ±0.30%  (widened from 0.15 to make FLAT a usable class)
MAG_BUCKETS = [0.0025, 0.0075, 0.015]   # |return| boundaries
DIR_LABELS = ["DOWN", "FLAT", "UP"]
MAG_LABELS = ["TINY", "SMALL", "MEDIUM", "LARGE"]


def _safe_pct(s: pd.Series, n: int = 1) -> pd.Series:
    return s.pct_change(n).replace([np.inf, -np.inf], np.nan)


def _rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = -delta.clip(upper=0).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def build_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Build the feature matrix. Index is `date`. Each row T contains features
    that are known by ~03:30 IST on day T, plus targets for day T's close vs
    day (T-1)'s close.

    Returns a DataFrame with columns:
      <feature columns…>, prev_close, next_close, y_logret, y_dir, y_mag
    """
    df = raw.copy().sort_index()

    # Forward-fill foreign markets: if NYSE was closed yesterday, last known
    # close is what we actually had to act on overnight.
    foreign_cols = [c for c in df.columns if c.endswith("_close") and c != "nifty_close"]
    df[foreign_cols] = df[foreign_cols].ffill()

    # ── Nifty derived (lagged by 1) ────────────────────────────────────────
    nclose = df["nifty_close"]
    nhigh, nlow = df["nifty_high"], df["nifty_low"]

    f = pd.DataFrame(index=df.index)
    f["nifty_ret_1"]  = _safe_pct(nclose, 1).shift(1)
    f["nifty_ret_5"]  = _safe_pct(nclose, 5).shift(1)
    f["nifty_ret_20"] = _safe_pct(nclose, 20).shift(1)
    f["nifty_rsi_14"] = _rsi(nclose, 14).shift(1)
    f["nifty_range_pct"] = ((nhigh - nlow) / nclose).shift(1)
    # 20d realised vol (annualised-ish)
    f["nifty_vol_20"] = _safe_pct(nclose, 1).rolling(20).std().shift(1)
    # Position vs 20d MA
    f["nifty_vs_ma20"] = (nclose / nclose.rolling(20).mean() - 1).shift(1)
    f["nifty_vs_ma50"] = (nclose / nclose.rolling(50).mean() - 1).shift(1)
    # Volume z-score
    vol = df["nifty_volume"].replace(0, np.nan)
    f["nifty_volz_20"] = ((vol - vol.rolling(20).mean()) / vol.rolling(20).std()).shift(1)

    # ── Cross-asset overnight returns (US session ended ~T-1 02:00 IST → known) ─
    for col in foreign_cols:
        name = col.replace("_close", "")
        s = df[col]
        # Most recent close vs previous close — overnight move
        f[f"{name}_ret_1"] = _safe_pct(s, 1)
        # 5d / 20d trend
        f[f"{name}_ret_5"] = _safe_pct(s, 5)
        f[f"{name}_ret_20"] = _safe_pct(s, 20)

    # VIX level (regime), USD/INR level
    f["vix_level"] = df["vix_close"]
    f["vix_vs_ma20"] = (df["vix_close"] / df["vix_close"].rolling(20).mean() - 1)
    f["usdinr_level"] = df["usdinr_close"]
    f["us10y_level"] = df["us10y_close"]

    # ── Calendar ───────────────────────────────────────────────────────────
    f["dow"] = df.index.dayofweek.astype(float)
    f["month"] = df.index.month.astype(float)
    # one-hot day-of-week
    for d in range(5):  # Mon-Fri only matter for NSE
        f[f"dow_{d}"] = (df.index.dayofweek == d).astype(float)

    # Drop the gift_nifty column entirely if it's all NaN (yfinance had no feed)
    if "gift_nifty" in df.columns and df["gift_nifty"].notna().sum() == 0:
        pass  # already excluded — never added to f
    elif "gift_nifty" in df.columns:
        gn = df["gift_nifty"].astype(float)
        f["gift_ret_1"] = _safe_pct(gn, 1)
        f["gift_vs_nifty"] = (gn / df["nifty_close"].shift(1) - 1)

    # ── v3: interaction & regime features ─────────────────────────────────
    # US-Asia agreement: do US (S&P) and Asia overnight (KOSPI/HSI/Nikkei) point the same direction?
    if {"sp500_close", "kospi_close", "hsi_close", "nikkei_close"}.issubset(df.columns):
        sp = np.sign(_safe_pct(df["sp500_close"], 1))
        ko = np.sign(_safe_pct(df["kospi_close"], 1))
        hs = np.sign(_safe_pct(df["hsi_close"], 1))
        nk = np.sign(_safe_pct(df["nikkei_close"], 1))
        f["us_asia_bull_agree"] = ((sp > 0) & ((ko > 0).astype(int) + (hs > 0).astype(int) + (nk > 0).astype(int) >= 2)).astype(float)
        f["us_asia_bear_agree"] = ((sp < 0) & ((ko < 0).astype(int) + (hs < 0).astype(int) + (nk < 0).astype(int) >= 2)).astype(float)
        # Asia majority bull — count of positive Asia indices (3 = unanimous bull)
        f["asia_bull_count"] = ((ko > 0).astype(float) + (hs > 0).astype(float) + (nk > 0).astype(float))

    # VIX regime — one-hot
    vix = df["vix_close"]
    f["vix_regime_low"]  = (vix < 13).astype(float)
    f["vix_regime_mid"]  = ((vix >= 13) & (vix < 20)).astype(float)
    f["vix_regime_high"] = (vix >= 20).astype(float)

    # Realized vol vs VIX — divergence between Nifty's realized 20d vol (annualised %) and VIX level.
    # When realized > implied → vol expanding → potential reversal/exhaustion.
    realised_ann = (_safe_pct(nclose, 1).rolling(20).std() * np.sqrt(252) * 100).shift(1)
    f["nifty_rv_vs_vix"] = (realised_ann - vix)

    # USD/INR + Nifty divergence: USD/INR up = INR weak (usually bearish for Nifty).
    # If both up together → unusual (positive divergence).
    if "usdinr_close" in df.columns:
        inr_ret = _safe_pct(df["usdinr_close"], 1)
        nifty_lag_ret = _safe_pct(nclose, 1).shift(1)
        f["inr_nifty_divergence"] = (inr_ret * nifty_lag_ret * 100)   # both positive → positive product

    # Trend strength on Nifty (ADX-like, simplified): rolling % of up days in last 20
    f["nifty_up_freq_20"] = (_safe_pct(nclose, 1).shift(1) > 0).rolling(20).mean()

    # ── Targets ────────────────────────────────────────────────────────────
    # For row T: prev_close = nifty_close[T-1], next_close = nifty_close[T]
    f["prev_close"] = df["nifty_close"].shift(1)
    f["next_close"] = df["nifty_close"]
    logret = np.log(f["next_close"] / f["prev_close"])
    f["y_logret"] = logret
    pct = np.expm1(logret)

    # Direction class
    dir_class = pd.Series(1, index=f.index, dtype=int)  # default FLAT
    dir_class[pct > DIR_THRESHOLD] = 2   # UP
    dir_class[pct < -DIR_THRESHOLD] = 0  # DOWN
    f["y_dir"] = dir_class

    # Magnitude bucket on |pct|
    abs_pct = pct.abs()
    mag_class = pd.Series(0, index=f.index, dtype=int)  # TINY
    mag_class[abs_pct >= MAG_BUCKETS[0]] = 1
    mag_class[abs_pct >= MAG_BUCKETS[1]] = 2
    mag_class[abs_pct >= MAG_BUCKETS[2]] = 3
    f["y_mag"] = mag_class

    # Replace inf, drop early rows with NaN from rolling windows
    f = f.replace([np.inf, -np.inf], np.nan)
    f = f.dropna()
    return f


FEATURE_PREFIXES = (
    "nifty_", "sp500_", "nasdaq_", "dow_", "vix_", "us10y_", "dxy_", "usdinr_",
    "brent_", "gold_", "nikkei_", "gift_", "vix_level", "vix_vs_ma20",
    "usdinr_level", "us10y_level", "month",
)
TARGET_COLS = {"prev_close", "next_close", "y_logret", "y_dir", "y_mag"}


def split_features_targets(df: pd.DataFrame) -> tuple[list[str], pd.DataFrame, pd.DataFrame]:
    """Returns (feature_columns, X_df, targets_df)."""
    feat_cols = [c for c in df.columns if c not in TARGET_COLS]
    return feat_cols, df[feat_cols], df[list(TARGET_COLS)]


if __name__ == "__main__":
    import os
    DATA = os.path.join(os.path.dirname(__file__), "data", "overnight_raw.parquet")
    raw = pd.read_parquet(DATA)
    f = build_features(raw)
    feat_cols, X, y = split_features_targets(f)
    print(f"Features: {len(feat_cols)} columns, {len(X)} rows")
    print(f"Date range: {X.index.min().date()} → {X.index.max().date()}")
    print(f"\nFeature columns: {feat_cols}")
    print(f"\nTarget distribution (y_dir):\n{y['y_dir'].value_counts().sort_index().rename(index=dict(enumerate(DIR_LABELS)))}")
    print(f"\nTarget distribution (y_mag):\n{y['y_mag'].value_counts().sort_index().rename(index=dict(enumerate(MAG_LABELS)))}")
    print(f"\ny_logret stats: mean={y['y_logret'].mean():.5f}, std={y['y_logret'].std():.5f}")
    print(f"\nLast 3 rows (selected cols):")
    print(f[["prev_close", "next_close", "y_logret", "y_dir", "y_mag"]].tail(3))
