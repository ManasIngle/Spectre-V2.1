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

# Indian ADRs — US-listed, trade on NYSE/NASDAQ, close ~02:30 IST (known before NSE opens).
# Combined ~20% of Nifty index weight. Each ADR is a direct overnight signal for its sector.
ADR_TICKERS = {
    "infy_adr":  "INFY",   # Infosys — ~4% Nifty weight
    "hdb_adr":   "HDB",    # HDFC Bank — ~13% Nifty weight
    "ibn_adr":   "IBN",    # ICICI Bank — ~8% Nifty weight
    "wit_adr":   "WIT",    # Wipro
    "ttm_adr":   "TTM",    # Tata Motors
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

# ── Indian sector indices ─────────────────────────────────────────────────────
# Local CSV source: Market Dataset since 2015 (NSE data, up to ~Apr 2026).
# yfinance tickers used for incremental top-up beyond local data cutoff.
# All indices confirmed working on yfinance as of May 2026.
LOCAL_DATASET_PATH = os.environ.get(
    "MARKET_DATASET_PATH",
    "/Users/manasingle/Edge/Market Dataset since 2015",
)

SECTOR_FILES = {
    "nifty_bank":   "NIFTY BANK_day.csv",
    "nifty_it":     "NIFTY IT_day.csv",
    "nifty_fin":    "NIFTY FIN SERVICE_day.csv",
    "nifty_fmcg":   "NIFTY FMCG_day.csv",
    "nifty_auto":   "NIFTY AUTO_day.csv",
    "nifty_energy": "NIFTY ENERGY_day.csv",
    "nifty_health": "NIFTY HEALTHCARE_day.csv",
    "nifty_infra":  "NIFTY INFRA_day.csv",
    "nifty_500":    "NIFTY 500_day.csv",
    "nifty_100":    "NIFTY 100_day.csv",
}

SECTOR_YF_TICKERS = {
    "nifty_bank":   "^NSEBANK",
    "nifty_it":     "^CNXIT",
    "nifty_auto":   "^CNXAUTO",
    "nifty_fmcg":   "^CNXFMCG",
    "nifty_energy": "^CNXENERGY",
    "nifty_health": "^CNXPHARMA",
    "nifty_100":    "^CNX100",
    "nifty_500":    "^CRSLDX",
}


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


def _load_local_sector(name: str, filename: str) -> pd.Series | None:
    """Load a sector index close series from the local NSE dataset CSV."""
    path = os.path.join(LOCAL_DATASET_PATH, filename)
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.set_index("date").sort_index()
    return df["close"].rename(f"{name}_close")


def fetch_sector_data(start: str) -> pd.DataFrame:
    """Build sector index closes from local CSVs, topped up with yfinance for recent dates.

    Returns a DataFrame indexed by date with columns <sector>_close for each sector.
    Only trading days where Nifty has data are included (join is outer here; data_fetcher
    will inner-join against the Nifty index later).
    """
    start_dt = pd.to_datetime(start)
    frames: dict[str, pd.Series] = {}

    print("\nSector indices (local CSV + yfinance top-up):")
    for name, filename in SECTOR_FILES.items():
        local = _load_local_sector(name, filename)
        if local is not None:
            local = local[local.index >= start_dt]
            local_end = local.index.max()
        else:
            local_end = start_dt

        # Top-up with yfinance for dates beyond local data cutoff
        yf_series: pd.Series | None = None
        if name in SECTOR_YF_TICKERS:
            top_start = (local_end + timedelta(days=1)).strftime("%Y-%m-%d")
            df_yf = _download(SECTOR_YF_TICKERS[name], top_start)
            if df_yf is not None and "Close" in df_yf.columns and len(df_yf) > 0:
                df_yf = _flatten(df_yf)
                yf_series = df_yf["Close"].rename(f"{name}_close")
                yf_series.index = pd.to_datetime(yf_series.index).normalize()
            time.sleep(0.3)

        if local is not None and yf_series is not None:
            combined = pd.concat([local, yf_series]).sort_index()
            combined = combined[~combined.index.duplicated(keep="last")]
        elif local is not None:
            combined = local
        elif yf_series is not None:
            combined = yf_series
        else:
            print(f"  ✗ {name:15s} no local file and yfinance failed; skipping")
            continue

        frames[name] = combined
        rows_local = len(local) if local is not None else 0
        rows_yf = len(yf_series) if yf_series is not None else 0
        print(f"  ✓ {name:15s} {rows_local} local + {rows_yf} yfinance = {len(combined)} rows")

    if not frames:
        print("  ! No sector data loaded; breadth features will be absent.")
        return pd.DataFrame()

    out = pd.concat(frames.values(), axis=1).sort_index()
    return out


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

    # Indian ADR tickers — reliable yfinance, US-listed, known before NSE opens
    print("\nIndian ADRs:")
    for name, sym in ADR_TICKERS.items():
        df = _download(sym, start)
        if df is not None and "Close" in df.columns and len(df) > 200:
            print(f"  ✓ {name:12s} ({sym}) {len(df)} rows")
            out = out.join(df[["Close"]].rename(columns={"Close": f"{name}_close"}), how="outer")
        else:
            print(f"  ✗ {name:12s} ({sym}) not available; skipping")
        time.sleep(0.4)

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

    # Indian sector indices — local NSE data + yfinance top-up
    sector_df = fetch_sector_data(start)
    if not sector_df.empty:
        out = out.join(sector_df, how="left")

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
