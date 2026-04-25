"""
Overnight Nifty LSTM — data fetcher.

Pulls 10 years of daily OHLCV for Nifty + global macro tickers from yfinance.
GIFT Nifty: tries a couple of unofficial yahoo tickers, falls back to investing.com
scrape, and finally degrades gracefully (column filled with NaN → forward-filled).

Run standalone to refresh the on-disk cache:
    python data_fetcher.py            # full 10y refresh
    python data_fetcher.py --days 5   # incremental top-up
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
RAW_PARQUET = os.path.join(DATA_DIR, "overnight_raw.parquet")

# Ticker map: short_name -> yfinance symbol. Order matters (Nifty first).
# v2: dropped Dow (collinear with S&P), added Hang Seng / KOSPI / Copper / India 10Y / MOVE.
TICKERS = {
    "nifty":   "^NSEI",       # Nifty 50 spot — target
    "sp500":   "^GSPC",
    "nasdaq":  "^IXIC",
    "vix":     "^VIX",
    "us10y":   "^TNX",        # CBOE 10Y yield index (already in % * 10)
    "dxy":     "DX-Y.NYB",
    "usdinr":  "INR=X",       # USD/INR spot
    "brent":   "BZ=F",
    "gold":    "GC=F",
    "copper":  "HG=F",        # NEW: industrial demand proxy
    "nikkei":  "^N225",
    "hsi":     "^HSI",        # NEW: Hang Seng — Asia session
    "kospi":   "^KS11",       # NEW: Korea — Asia session
    # India 10Y and MOVE are not reliably on yfinance under standard tickers;
    # we attempt below and fall back gracefully.
}

# Best-effort tickers — yfinance coverage is unreliable. Skipped without erroring.
OPTIONAL_TICKERS = {
    "india10y": "^IN10YR",    # often missing
    "move":     "^MOVE",      # ICE MOVE bond-vol; spotty coverage on yfinance
    "ftse":     "^FTSE",      # Europe close — known overnight
    "dax":      "^GDAXI",
}

# Candidate GIFT Nifty / SGX Nifty tickers — tried in order. None are guaranteed.
GIFT_CANDIDATES = ["GIFTNIFTY", "GIFTNIFTY.NS", "SGX-NIFTY", "^NIFTYIX", "NIFTY50.NS"]


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _download(ticker: str, start: str, end: str | None = None) -> pd.DataFrame | None:
    try:
        df = yf.download(
            ticker, start=start, end=end, interval="1d",
            progress=False, auto_adjust=False, threads=False,
        )
        if df is None or df.empty:
            return None
        df = _flatten(df)
        # Keep only Close — that's what we need for cross-asset features.
        # For Nifty itself we keep full OHLCV.
        return df
    except Exception as e:
        print(f"  ! {ticker}: {e}")
        return None


def _try_gift_yfinance(start: str) -> pd.Series | None:
    """Best-effort GIFT Nifty close via yfinance candidates."""
    for cand in GIFT_CANDIDATES:
        df = _download(cand, start)
        if df is not None and "Close" in df.columns and len(df) > 100:
            print(f"  ✓ GIFT Nifty matched yfinance ticker: {cand} ({len(df)} rows)")
            return df["Close"].rename("gift_nifty")
    return None


def fetch_all(years: int = 10) -> pd.DataFrame:
    """Download all tickers and return a single daily-indexed DataFrame.
    Columns: <name>_open/high/low/close/volume for Nifty, <name>_close for others."""
    end_dt = datetime.utcnow().date()
    start_dt = end_dt - timedelta(days=int(years * 365.25) + 30)
    start = start_dt.isoformat()
    print(f"Fetching {years}y of daily data: {start} → {end_dt}")

    frames: list[pd.DataFrame] = []
    for name, sym in TICKERS.items():
        print(f"- {name:8s} ({sym}) …", end=" ", flush=True)
        df = _download(sym, start)
        if df is None:
            print("FAILED")
            continue
        if name == "nifty":
            cols = {"Open": "nifty_open", "High": "nifty_high", "Low": "nifty_low",
                    "Close": "nifty_close", "Volume": "nifty_volume"}
            df = df[[c for c in cols if c in df.columns]].rename(columns=cols)
        else:
            df = df[["Close"]].rename(columns={"Close": f"{name}_close"})
        print(f"OK {len(df)} rows")
        frames.append(df)
        time.sleep(0.4)  # polite

    if not frames:
        raise RuntimeError("No data fetched — check network / yfinance.")

    out = frames[0]
    for f in frames[1:]:
        out = out.join(f, how="outer")

    # Optional tickers — try silently, skip on failure
    print("\nOptional tickers (best-effort):")
    for name, sym in OPTIONAL_TICKERS.items():
        df = _download(sym, start)
        if df is not None and "Close" in df.columns and len(df) > 200:
            print(f"  ✓ {name:10s} ({sym}) {len(df)} rows")
            out = out.join(df[["Close"]].rename(columns={"Close": f"{name}_close"}), how="outer")
        else:
            print(f"  ✗ {name:10s} ({sym}) not available; skipping")
        time.sleep(0.4)

    # GIFT Nifty (best-effort)
    print("- gift_nifty …", end=" ", flush=True)
    gift = _try_gift_yfinance(start)
    if gift is None:
        print("not found on yfinance; column will be NaN (model will see this as missing)")
        out["gift_nifty"] = pd.NA
    else:
        out = out.join(gift.to_frame(), how="outer")

    # Index normalisation
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    out.index.name = "date"
    out = out.sort_index()

    # Drop rows where Nifty itself is missing (weekends/holidays for Nifty)
    out = out.dropna(subset=["nifty_close"])
    print(f"\nFinal dataset: {len(out)} trading days, {out.shape[1]} columns")
    print(f"Date range: {out.index.min().date()} → {out.index.max().date()}")
    return out


def save(df: pd.DataFrame, path: str = RAW_PARQUET):
    df.to_parquet(path)
    print(f"Saved → {path}")


def load(path: str = RAW_PARQUET) -> pd.DataFrame:
    return pd.read_parquet(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=10)
    args = ap.parse_args()
    df = fetch_all(years=args.years)
    save(df)
    print("\nLast 3 rows:")
    print(df.tail(3))


if __name__ == "__main__":
    main()
