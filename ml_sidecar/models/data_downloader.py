"""
Historical Data Downloader for ML Model Training
Downloads 3 years of Nifty + contributors data at multiple intervals.

Yahoo Finance limits:
  - 1d (daily): unlimited history
  - 1h (hourly): max 730 days per request
  - 5m: max 60 days
So for 3 years we combine: daily (3y) + hourly (2 x 730d) + 5m (60d recent)
"""
import yfinance as yf
import pandas as pd
import os
import sys
import time
import io

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Top 10 Nifty contributors by weight
TOP_CONTRIBUTORS = [
    "HDFCBANK.NS", "RELIANCE.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
    "BHARTIARTL.NS", "ITC.NS", "LT.NS", "SBIN.NS", "BAJFINANCE.NS",
]

NIFTY_SYMBOL = "^NSEI"

# Force UTF-8 output
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def download_safe(symbol, interval, period, label):
    """Download data with error handling. Returns DataFrame or None."""
    print(f"  [{label}] {symbol} interval={interval} period={period} ...", end=" ", flush=True)
    try:
        df = yf.download(symbol, interval=interval, period=period, progress=False)
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            print(f"OK: {len(df)} rows")
            return df
        else:
            print("EMPTY")
            return None
    except Exception as e:
        print(f"ERR: {str(e)[:60]}")
        return None


def download_all():
    """Download all required historical data for 3-year coverage."""
    print("=" * 60)
    print("NiftyTrader Pro - 3-Year Historical Data Download")
    print("=" * 60)

    saved_files = []

    # =========================================================
    # 1. NIFTY DAILY - 3 YEARS (best coverage for ML training)
    # =========================================================
    print("\n[1/5] Nifty DAILY data (3 years)...")
    df = download_safe(NIFTY_SYMBOL, "1d", "3y", "Nifty-Daily")
    if df is not None:
        path = os.path.join(DATA_DIR, "nifty_daily.csv")
        df.to_csv(path)
        saved_files.append(("nifty_daily.csv", len(df)))

    # =========================================================
    # 2. NIFTY HOURLY - ~2 YEARS (730d max per request, 2 chunks)
    # =========================================================
    print("\n[2/5] Nifty HOURLY data (730d max chunks)...")
    hourly_frames = []
    for i in range(2):
        chunk = download_safe(NIFTY_SYMBOL, "1h", "730d", f"Nifty-1h-chunk{i+1}")
        if chunk is not None:
            hourly_frames.append(chunk)
        time.sleep(1)

    if hourly_frames:
        nifty_1h = pd.concat(hourly_frames)
        nifty_1h = nifty_1h[~nifty_1h.index.duplicated(keep='last')]
        nifty_1h.sort_index(inplace=True)
        path = os.path.join(DATA_DIR, "nifty_1h.csv")
        nifty_1h.to_csv(path)
        saved_files.append(("nifty_1h.csv", len(nifty_1h)))

    # =========================================================
    # 3. NIFTY 5-MINUTE - 60 DAYS (recent high-res data)
    # =========================================================
    print("\n[3/5] Nifty 5-MINUTE data (60 days)...")
    df = download_safe(NIFTY_SYMBOL, "5m", "60d", "Nifty-5m")
    if df is not None:
        path = os.path.join(DATA_DIR, "nifty_5m.csv")
        df.to_csv(path)
        saved_files.append(("nifty_5m.csv", len(df)))

    # =========================================================
    # 4. NIFTY 15-MINUTE - 60 DAYS
    # =========================================================
    print("\n[4/5] Nifty 15-MINUTE data (60 days)...")
    df = download_safe(NIFTY_SYMBOL, "15m", "60d", "Nifty-15m")
    if df is not None:
        path = os.path.join(DATA_DIR, "nifty_15m.csv")
        df.to_csv(path)
        saved_files.append(("nifty_15m.csv", len(df)))

    # =========================================================
    # 5. TOP 10 CONTRIBUTORS - Daily 3y + Hourly 730d
    # =========================================================
    print("\n[5/5] Top 10 contributors (daily 3y + hourly 730d)...")
    for sym in TOP_CONTRIBUTORS:
        name = sym.replace(".NS", "")

        # Daily 3 years
        df_d = download_safe(sym, "1d", "3y", f"{name}-daily")
        if df_d is not None:
            path = os.path.join(DATA_DIR, f"{name}_daily.csv")
            df_d.to_csv(path)
            saved_files.append((f"{name}_daily.csv", len(df_d)))

        # Hourly 730d
        df_h = download_safe(sym, "1h", "730d", f"{name}-1h")
        if df_h is not None:
            path = os.path.join(DATA_DIR, f"{name}_1h.csv")
            df_h.to_csv(path)
            saved_files.append((f"{name}_1h.csv", len(df_h)))

        time.sleep(0.5)

    # =========================================================
    # SUMMARY
    # =========================================================
    print("\n" + "=" * 60)
    print(f"Download complete! {len(saved_files)} files saved:")
    print("-" * 40)
    total_rows = 0
    for fname, rows in saved_files:
        print(f"  {fname:30s} {rows:>7,} rows")
        total_rows += rows
    print("-" * 40)
    print(f"  {'TOTAL':30s} {total_rows:>7,} rows")
    print(f"\nData directory: {DATA_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    download_all()
