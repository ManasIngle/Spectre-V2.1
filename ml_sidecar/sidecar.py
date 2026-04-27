"""
Spectre ML Sidecar — lightweight FastAPI server that loads the pkl/keras
models once and serves predictions via HTTP to the Go main server.

Run: uvicorn sidecar:app --port 8240
"""
import os, json, time, numpy as np, joblib, datetime as dt
from fastapi import FastAPI
import zoneinfo

ML_DIR = os.path.join(os.path.dirname(__file__), "models")

# Fallback sequence: try 5m models first (since we fetch 5m data), then standard ones
def _get_model_paths():
    paths = {
        "model": "nifty_direction_model_5m.pkl",
        "meta": "model_metadata_5m.json",
        "lstm": "nifty_lstm_model_5m.keras",
        "scaler": "lstm_scaler_5m.pkl",
        "lstm_meta": "lstm_metadata_5m.json"
    }
    
    # If 5m doesn't exist, fallback to old 1h
    if not os.path.exists(os.path.join(ML_DIR, paths["model"])):
        paths = {
            "model": "nifty_direction_model.pkl",
            "meta": "model_metadata.json",
            "lstm": "nifty_lstm_model.keras",
            "scaler": "lstm_scaler.pkl",
            "lstm_meta": "lstm_metadata.json"
        }
        
    return {k: os.path.join(ML_DIR, v) for k, v in paths.items()}

app = FastAPI(title="Spectre ML Sidecar")

_rolling_xgb = None
_direction_xgb = None
_old_direction_xgb = None
_cross_xgb = None
_meta = None
_old_meta = None

# 3-Minute Scalper LSTM
_scalper_lstm = None
_scalper_scaler = None
_scalper_meta = None

def _load():
    global _rolling_xgb, _direction_xgb, _old_direction_xgb, _cross_xgb, _meta, _old_meta

    # Model version suffix — change this to "" to revert to original models
    VER = "-Rtr14April"

    # Load Rolling Master (retrained on 1M rows of 1m data)
    vanilla_path = os.path.join(ML_DIR, f"nifty_rolling_model{VER}.pkl")
    if not os.path.exists(vanilla_path):
        vanilla_path = os.path.join(ML_DIR, "nifty_rolling_model.pkl")  # fallback to original
    if os.path.exists(vanilla_path):
        _rolling_xgb = joblib.load(vanilla_path)
        print(f"Loaded rolling model: {vanilla_path}")

    # Load Direction Model (5m retrained on 207K rows)
    dir_path = os.path.join(ML_DIR, f"nifty_direction_model_5m{VER}.pkl")
    if not os.path.exists(dir_path):
        dir_path = os.path.join(ML_DIR, "nifty_direction_model_5m.pkl")  # fallback
    if os.path.exists(dir_path):
        _direction_xgb = joblib.load(dir_path)
        print(f"Loaded direction model: {dir_path}")

    # Load OLD 1h model (original — not retrained, kept as OldDirection signal)
    old_dir_path = os.path.join(ML_DIR, "nifty_direction_model.pkl")
    if os.path.exists(old_dir_path):
        _old_direction_xgb = joblib.load(old_dir_path)
        print(f"Loaded OLD direction model: {old_dir_path}")

    # Load Cross-Asset Model (retrained on 1M synced Nifty+BankNifty bars)
    cross_path = os.path.join(ML_DIR, f"nifty_cross_asset_model{VER}.pkl")
    if not os.path.exists(cross_path):
        cross_path = os.path.join(ML_DIR, "nifty_cross_asset_model.pkl")  # fallback
    if os.path.exists(cross_path):
        _cross_xgb = joblib.load(cross_path)
        print(f"Loaded cross-asset model: {cross_path}")

    # Load metadata for retrained 5m model (35 features)
    meta_path = os.path.join(ML_DIR, f"model_metadata_5m{VER}.json")
    if not os.path.exists(meta_path):
        meta_path = os.path.join(ML_DIR, "model_metadata_5m.json")  # fallback
    if os.path.exists(meta_path):
        with open(meta_path) as f: _meta = json.load(f)
        print(f"Loaded metadata: {meta_path} ({len(_meta.get('feature_columns',[]))} features)")

    # Old model metadata (31 features — for OldDirection model)
    old_meta_path = os.path.join(ML_DIR, "model_metadata.json")
    if os.path.exists(old_meta_path):
        with open(old_meta_path) as f: _old_meta = json.load(f)
        print(f"Loaded old metadata: {old_meta_path}")

    # 3-Minute Scalper LSTM
    global _scalper_lstm, _scalper_scaler, _scalper_meta
    scalper_model_path  = os.path.join(ML_DIR, f"nifty_scalper_lstm{VER}.keras")
    scalper_scaler_path = os.path.join(ML_DIR, f"nifty_scalper_scaler{VER}.pkl")
    scalper_meta_path   = os.path.join(ML_DIR, f"nifty_scalper_meta{VER}.json")
    if os.path.exists(scalper_model_path) and os.path.exists(scalper_scaler_path) and os.path.exists(scalper_meta_path):
        try:
            import tensorflow as tf
            _scalper_lstm   = tf.keras.models.load_model(scalper_model_path)
            _scalper_scaler = joblib.load(scalper_scaler_path)
            with open(scalper_meta_path) as f: _scalper_meta = json.load(f)
            print(f"Loaded 3m scalper LSTM: {scalper_model_path} ({_scalper_meta.get('n_features')} features, acc={_scalper_meta.get('accuracy')}%)")
        except Exception as e:
            print(f"Scalper LSTM load failed: {e}")
    else:
        print(f"Scalper LSTM not found at {scalper_model_path} — run train_scalper_lstm.py to generate")

@app.on_event("startup")
def startup_load():
    _load()

import aiohttp, asyncio, pandas as pd, random

# ─── NSE OI Fetching (Python aiohttp — bypasses Akamai TLS fingerprint check) ─
_NSE_COOKIES = {}
_NSE_COOKIE_TIME = 0
_NSE_COOKIE_TTL = 300
_OI_CACHE = {"data": None, "expiry": 0}

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/option-chain",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}

async def _refresh_nse_cookies():
    global _NSE_COOKIES, _NSE_COOKIE_TIME
    jar = aiohttp.CookieJar()
    connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(cookie_jar=jar, connector=connector, timeout=timeout) as session:
            async with session.get("https://www.nseindia.com", headers=_BROWSER_HEADERS) as r:
                await r.read()
                print(f"NSE home: HTTP {r.status}")
            await asyncio.sleep(0.5 + random.random() * 0.5)
            oc_hdrs = {**_BROWSER_HEADERS, "Referer": "https://www.nseindia.com/"}
            async with session.get("https://www.nseindia.com/option-chain", headers=oc_hdrs) as r:
                await r.read()
                print(f"NSE OC page: HTTP {r.status}")
        # Direct jar iteration — works across all aiohttp versions
        cookies = {}
        for cookie in jar:
            cookies[cookie.key] = cookie.value
        if cookies:
            _NSE_COOKIES = cookies
            _NSE_COOKIE_TIME = time.time()
            print(f"NSE cookies refreshed: {len(cookies)} cookies ({', '.join(cookies.keys())})")
        else:
            print("NSE cookie refresh: no cookies received")
    except Exception as e:
        print(f"NSE cookie refresh failed: {e}")

async def _fetch_oi() -> dict:
    global _NSE_COOKIES, _NSE_COOKIE_TIME, _OI_CACHE
    now = time.time()
    if _OI_CACHE["data"] and _OI_CACHE["expiry"] > now:
        return _OI_CACHE["data"]
    if not _NSE_COOKIES or (now - _NSE_COOKIE_TIME) > _NSE_COOKIE_TTL:
        await _refresh_nse_cookies()

    for attempt in range(3):
        try:
            cookie_str = "; ".join(f"{k}={v}" for k, v in (_NSE_COOKIES or {}).items())
            hdrs = {**_API_HEADERS}
            if cookie_str:
                hdrs["Cookie"] = cookie_str
            connector = aiohttp.TCPConnector(ssl=False)
            timeout = aiohttp.ClientTimeout(total=15)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                # Step 1: get nearest expiry
                contract_url = "https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY"
                async with session.get(contract_url, headers=hdrs) as r:
                    print(f"NSE Contract API attempt {attempt+1}: HTTP {r.status}")
                    if r.status in (401, 403):
                        _NSE_COOKIES = {}
                        await _refresh_nse_cookies()
                        await asyncio.sleep(1 + attempt)
                        continue
                    if r.status != 200:
                        print(f"OI contract-info HTTP {r.status} on attempt {attempt+1}")
                        await asyncio.sleep(1 + attempt)
                        continue
                    ci = await r.json(content_type=None)
                    expiry_dates = ci.get("expiryDates", [])
                    if not expiry_dates:
                        print(f"OI: no expiry dates returned on attempt {attempt+1}")
                        continue
                    nearest = expiry_dates[0]

                await asyncio.sleep(0.3 + random.random() * 0.4)

                # Step 2: fetch option chain v3 — same session (cookies stay active)
                v3_url = f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY&expiry={nearest}"
                async with session.get(v3_url, headers=hdrs) as r:
                    print(f"NSE OI API (v3) attempt {attempt+1}: HTTP {r.status}")
                    if r.status in (401, 403):
                        print(f"OI v3 chain HTTP {r.status} — refreshing cookies")
                        _NSE_COOKIES = {}
                        await _refresh_nse_cookies()
                        await asyncio.sleep(1 + attempt)
                        continue
                    if r.status == 429:
                        print("NSE rate limited, waiting...")
                        await asyncio.sleep(3 + attempt * 2)
                        continue
                    if r.status != 200:
                        print(f"OI v3 chain HTTP {r.status} on attempt {attempt+1}")
                        await asyncio.sleep(1 + attempt)
                        continue
                    raw = await r.json(content_type=None)

            records = raw.get("records", {})
            data = records.get("data", []) or raw.get("filtered", {}).get("data", [])
            underlying = records.get("underlyingValue", 0)
            atm = round(underlying / 50) * 50
            strikes, tot_ce, tot_pe, tot_ce_chg, tot_pe_chg = [], 0, 0, 0, 0
            for rec in data:
                sp = rec.get("strikePrice", 0)
                if not (atm - 1000 <= sp <= atm + 1000): continue
                ce, pe = rec.get("CE") or {}, rec.get("PE") or {}
                ce_oi = ce.get("openInterest", 0)
                pe_oi = pe.get("openInterest", 0)
                ce_chg = ce.get("changeinOpenInterest", 0)
                pe_chg = pe.get("changeinOpenInterest", 0)
                tot_ce += ce_oi; tot_pe += pe_oi
                tot_ce_chg += ce_chg; tot_pe_chg += pe_chg
                strikes.append({"strike": sp,
                    "CE_OI": ce_oi, "CE_OI_Chg": ce_chg, "CE_LTP": ce.get("lastPrice", 0),
                    "PE_OI": pe_oi, "PE_OI_Chg": pe_chg, "PE_LTP": pe.get("lastPrice", 0)})
            strikes.sort(key=lambda x: x["strike"])
            pcr = round(tot_pe / tot_ce, 2) if tot_ce > 0 else 0
            result = {"underlying": round(underlying, 2), "atm_strike": atm,
                      "expiry": nearest, "timestamp": records.get("timestamp", ""),
                      "pcr_oi": pcr, "total_ce_oi": tot_ce, "total_pe_oi": tot_pe,
                      "total_ce_oi_chg": tot_ce_chg, "total_pe_oi_chg": tot_pe_chg,
                      "strikes": strikes}
            _OI_CACHE = {"data": result, "expiry": now + 150}
            return result
        except Exception as e:
            print(f"OI attempt {attempt+1} failed: {e}")
            await asyncio.sleep(1 + attempt)
    cached = _OI_CACHE.get("data")
    return cached if cached else {"error": "NSE OI fetch failed after 3 attempts", "strikes": []}

@app.get("/oi")
async def get_oi():
    return await _fetch_oi()

# ─── Yahoo Finance OHLCV proxy (Go net/http is TLS-fingerprinted; aiohttp is not) ─
_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
    "Origin": "https://finance.yahoo.com",
}

def _resample_to_n_min(bars_1m: list, n: int) -> list:
    """Group 1m bars into n-minute candles (OHLCV). Partial last group is dropped."""
    result = []
    group = []
    for bar in bars_1m:
        group.append(bar)
        if len(group) == n:
            result.append({
                "t": group[0]["t"],
                "o": group[0]["o"],
                "h": max(b["h"] for b in group),
                "l": min(b["l"] for b in group),
                "c": group[-1]["c"],
                "v": sum(b["v"] for b in group),
            })
            group = []
    return result

async def _fetch_yahoo_bars(ticker: str, interval: str, range_: str) -> list:
    """Fetch OHLCV bars from Yahoo Finance. Returns list of bar dicts."""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_}"
    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, headers=_YAHOO_HEADERS) as r:
            if r.status != 200:
                raise ValueError(f"Yahoo returned {r.status}")
            data = await r.json(content_type=None)
    result = data.get("chart", {}).get("result", [])
    if not result:
        raise ValueError("no data")
    res = result[0]
    timestamps = res.get("timestamp", [])
    q = res.get("indicators", {}).get("quote", [{}])[0]
    closes = q.get("close", [])
    bars = []
    for i, ts in enumerate(timestamps):
        if i >= len(closes) or not closes[i]:
            continue
        bars.append({
            "t": ts,
            "o": q.get("open", [None] * len(timestamps))[i] or 0,
            "h": q.get("high", [None] * len(timestamps))[i] or 0,
            "l": q.get("low",  [None] * len(timestamps))[i] or 0,
            "c": closes[i],
            "v": q.get("volume", [0] * len(timestamps))[i] or 0,
        })
    return bars

@app.get("/ohlcv")
async def get_ohlcv(ticker: str, interval: str = "5m", range: str = "5d"):
    """Proxy Yahoo Finance OHLCV — Python aiohttp bypasses VPS TLS block.
    Yahoo doesn't support 3m; we fetch 1m and resample."""
    try:
        if interval == "3m":
            bars_1m = await _fetch_yahoo_bars(ticker, "1m", range)
            bars = _resample_to_n_min(bars_1m, 3)
        else:
            bars = await _fetch_yahoo_bars(ticker, interval, range)
        return {"bars": bars}
    except Exception as e:
        return {"error": str(e), "bars": []}

# ─── NSE heatmap (full equity universe) ───────────────────────────────────────
_HEATMAP_CACHE = {"expiry": 0, "data": None}
_HEATMAP_TTL = 180  # 3 min — matches the Python v1.2 behaviour

_NSE_TICKERS_CACHE = {"expiry": 0, "data": []}
_NSE_TICKERS_TTL = 86400  # 24h

_NSE_FALLBACK_SYMBOLS = [
    "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC","SBIN",
    "BHARTIARTL","KOTAKBANK","LT","AXISBANK","BAJFINANCE","ASIANPAINT","MARUTI",
    "SUNPHARMA","TATAMOTORS","WIPRO","HCLTECH","ADANIENT","ADANIPORTS","POWERGRID",
    "NTPC","ULTRACEMCO","TITAN","NESTLEIND","TECHM","BAJAJFINSV","INDUSINDBK",
    "TATASTEEL","JSWSTEEL","ONGC","COALINDIA","GRASIM","CIPLA","DRREDDY","BPCL",
    "DIVISLAB","APOLLOHOSP","EICHERMOT","HEROMOTOCO","HDFCLIFE","SBILIFE",
    "BRITANNIA","TATACONSUM","TRENT","DMART","LTIM","PIDILITIND","DABUR",
    "GODREJCP","HAVELLS","COLPAL","MARICO","MUTHOOTFIN","BANDHANBNK","FEDERALBNK",
    "PNB","BANKBARODA","CANBK","CHOLAFIN","SBICARD","IRCTC","POLYCAB","AMBUJACEM",
    "ACC","TATAPOWER","ADANIGREEN","IRFC","RECLTD","PFC","HINDALCO","VEDL","NMDC",
    "JINDALSTEL","TATAELXSI","PERSISTENT","COFORGE","MPHASIS","DIXON","SIEMENS",
    "ABB","BEL","HAL","MOTHERSON","BOSCHLTD","MRF","BALKRISIND","SRF","DLF",
    "GODREJPROP","OBEROIRLTY","PHOENIXLTD","ICICIGI","ICICIPRULI","HDFCAMC",
    "MCX","BSE","CDSL","NAUKRI","INDIAMART","ZOMATO","PAYTM","NYKAA","MAXHEALTH",
    "FORTIS","IGL","MGL","GUJGASLTD","PETRONET","TATACOMM","INDIGO","PAGEIND",
]

async def _fetch_nse_ticker_list(session: aiohttp.ClientSession) -> list:
    """Download NSE equity master CSV. Falls back to a hardcoded broad list."""
    now = time.time()
    if _NSE_TICKERS_CACHE["data"] and _NSE_TICKERS_CACHE["expiry"] > now:
        return _NSE_TICKERS_CACHE["data"]
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/csv,*/*",
    }
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                text = await r.text()
                symbols = []
                for line in text.strip().split("\n")[1:]:
                    parts = line.split(",")
                    if parts and parts[0]:
                        sym = parts[0].strip().strip('"')
                        if sym and sym.replace("_", "").isalpha():
                            symbols.append(sym)
                if len(symbols) > 100:
                    tickers = [f"{s}.NS" for s in symbols]
                    _NSE_TICKERS_CACHE["data"] = tickers
                    _NSE_TICKERS_CACHE["expiry"] = now + _NSE_TICKERS_TTL
                    return tickers
    except Exception as e:
        print(f"NSE CSV fetch failed, using fallback: {e}")
    fallback = [f"{s}.NS" for s in _NSE_FALLBACK_SYMBOLS]
    _NSE_TICKERS_CACHE["data"] = fallback
    _NSE_TICKERS_CACHE["expiry"] = now + 3600  # shorter fallback cache — keep retrying CSV
    return fallback

async def _fetch_quote_for_heatmap(session: aiohttp.ClientSession, ticker: str, sem: asyncio.Semaphore):
    """Fetch last 2 daily closes for one ticker. Returns (ticker, ltp, chgPct) or None on failure."""
    async with sem:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
        try:
            async with session.get(url, headers=_YAHOO_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    return None
                data = await r.json(content_type=None)
            chart = data.get("chart", {}).get("result", [])
            if not chart:
                return None
            q = chart[0].get("indicators", {}).get("quote", [{}])[0]
            closes = [c for c in q.get("close", []) if c]
            if len(closes) < 2:
                return None
            ltp = closes[-1]
            prev = closes[-2]
            if prev <= 0:
                return None
            chg_pct = (ltp - prev) / prev * 100
            return (ticker.replace(".NS", ""), round(float(ltp), 2), round(float(chg_pct), 2))
        except Exception:
            return None

@app.get("/heatmap")
async def get_heatmap():
    """Fetch daily LTP + change% for the full NSE equity universe.
    Cached for 3 min; ~2200 tickers fan-out through Yahoo with a 50-concurrency semaphore."""
    now = time.time()
    if _HEATMAP_CACHE["data"] and _HEATMAP_CACHE["expiry"] > now:
        return _HEATMAP_CACHE["data"]

    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        tickers = await _fetch_nse_ticker_list(session)
        sem = asyncio.Semaphore(50)
        tasks = [_fetch_quote_for_heatmap(session, t, sem) for t in tickers]
        completed = await asyncio.gather(*tasks, return_exceptions=False)

    rows = []
    for r in completed:
        if r is None:
            continue
        ticker, ltp, chg_pct = r
        rows.append({"ticker": ticker, "ltp": ltp, "changePercent": chg_pct})
    rows.sort(key=lambda x: abs(x["changePercent"]), reverse=True)

    result = {"data": rows, "total": len(rows), "requested": len(tickers)}
    _HEATMAP_CACHE["data"] = result
    _HEATMAP_CACHE["expiry"] = now + _HEATMAP_TTL
    return result

async def _fetch_1m(ticker="%5ENSEI", days="1d"):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range={days}"
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, headers=_YAHOO_HEADERS) as r:
            return await r.json(content_type=None)

async def _fetch_5m(ticker="%5ENSEI", days="5d"):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range={days}"
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, headers=_YAHOO_HEADERS) as r:
            return await r.json(content_type=None)

async def _fetch_vix() -> list:
    """Fetch India VIX 1m closes from Yahoo Finance. Returns list of recent VIX values."""
    try:
        data = await _fetch_1m("%5EINDIAVIX", days="1d")
        if "chart" in data and data["chart"].get("result"):
            q = data["chart"]["result"][0]["indicators"]["quote"][0]
            closes = [v for v in q.get("close", []) if v is not None]
            if closes:
                return closes
    except Exception:
        pass
    return []

def build_rolling_bar(bars):
    """
    Crush up to 5 1-minute candles into a single rolling 5-minute structure.
    Works with fewer than 5 bars (e.g. first minutes of session).
    bars shape: [Close, High, Low, Open, Volume]
    """
    if len(bars) < 1: return None

    recent = np.array(bars[-5:])  # use up to last 5, fewer is fine
    c_ = recent[:,0]
    h_ = recent[:,1]
    l_ = recent[:,2]
    o_ = recent[:,3]
    v_ = recent[:,4]

    return [c_[-1], np.max(h_), np.min(l_), o_[0], np.sum(v_)]

def _extract_features(bars, feature_cols, vix_closes=None):
    import pandas as pd
    from ta.trend import ADXIndicator, MACD, EMAIndicator
    from ta.momentum import RSIIndicator
    from ta.volatility import BollingerBands, AverageTrueRange

    # Build rolling 5m bars from 1m history — works from minute 1.
    # Early in session: fewer bars → more NaN features → filled to neutral via nan_to_num.
    rolling_history = []
    for i in range(len(bars)):
        r = build_rolling_bar(bars[max(0, i-4):i+1])
        if r: rolling_history.append(r)

    df = pd.DataFrame(rolling_history, columns=["Close","High","Low","Open","Volume"])
    if len(df) < 2: return None, df  # need at least 2 rows for diff/pct_change

    c, h, l, v = df.Close, df.High, df.Low, df.Volume
    feat = {}

    try: feat["feat_rsi"] = float(RSIIndicator(c,14).rsi().iloc[-1])
    except: feat["feat_rsi"] = 50

    try:
        adx = ADXIndicator(h,l,c,14)
        feat["feat_adx"] = float(adx.adx().iloc[-1])
        feat["feat_di_plus"] = float(adx.adx_pos().iloc[-1])
        feat["feat_di_minus"] = float(adx.adx_neg().iloc[-1])
        feat["feat_di_diff"] = feat["feat_di_plus"] - feat["feat_di_minus"]
    except: feat.update({"feat_adx":20,"feat_di_plus":20,"feat_di_minus":20,"feat_di_diff":0})

    try: feat["feat_macd_hist"] = float(MACD(c).macd_diff().iloc[-1])
    except: feat["feat_macd_hist"] = 0

    try:
        e9 = EMAIndicator(c,9).ema_indicator().iloc[-1]
        e21 = EMAIndicator(c,21).ema_indicator().iloc[-1]
        feat["feat_ema_spread"] = float((e9-e21)/c.iloc[-1]*100)
    except: feat["feat_ema_spread"] = 0

    try:
        vw = (c*v).rolling(20).sum() / v.rolling(20).sum()
        feat["feat_vwap_dev"] = float((c.iloc[-1]-vw.iloc[-1])/c.iloc[-1]*100)
    except: feat["feat_vwap_dev"] = 0

    try:
        at = AverageTrueRange(h,l,c,10).average_true_range()
        hl2 = (h+l)/2; upper=hl2+2*at; lower=hl2-2*at
        feat["feat_st_direction"] = 1 if c.iloc[-1]>upper.iloc[-2] else (-1 if c.iloc[-1]<lower.iloc[-2] else 0)
    except: feat["feat_st_direction"] = 0

    try:
        a20 = v.rolling(20).mean().iloc[-1]
        feat["feat_rel_vol"] = float(v.iloc[-1]/a20) if a20>0 else 1
        a5 = v.rolling(5).mean().iloc[-1]
        feat["feat_vol_trend"] = float(a5/a20) if a20>0 else 1
    except: feat["feat_rel_vol"]=feat["feat_vol_trend"]=1

    for n,k in [(6,"feat_roc_6"),(12,"feat_roc_12")]:
        try: feat[k] = float(c.pct_change(n).iloc[-1]*100)
        except: feat[k] = 0

    try:
        bb = BollingerBands(c,20,2)
        rng = bb.bollinger_hband().iloc[-1]-bb.bollinger_lband().iloc[-1]
        feat["feat_bb_pos"] = float((c.iloc[-1]-bb.bollinger_lband().iloc[-1])/rng) if rng>0 else 0.5
    except: feat["feat_bb_pos"] = 0.5

    try:
        at14 = AverageTrueRange(h,l,c,14).average_true_range().iloc[-1]
        feat["feat_atr_move"] = float((c.iloc[-1]-c.iloc[-2])/at14) if at14>0 else 0
    except: feat["feat_atr_move"] = 0

    for lag,k in [(1,"feat_ret_1"),(2,"feat_ret_2"),(3,"feat_ret_3")]:
        try: feat[k] = float(c.pct_change(lag).iloc[-1]*100)
        except: feat[k] = 0

    try: feat["feat_slow_rsi"] = float(RSIIndicator(c,42).rsi().iloc[-1])
    except: feat["feat_slow_rsi"] = 50
    try:
        ms = MACD(c,52,24,18)
        feat["feat_slow_macd_hist"] = float(ms.macd_diff().iloc[-1])
    except: feat["feat_slow_macd_hist"] = 0
    try:
        as_ = AverageTrueRange(h,l,c,30).average_true_range()
        hl2s=(h+l)/2; us=hl2s+2*as_; ls=hl2s-2*as_
        feat["feat_slow_st_dir"] = 1 if c.iloc[-1]>us.iloc[-2] else (-1 if c.iloc[-1]<ls.iloc[-2] else 0)
    except: feat["feat_slow_st_dir"] = 0

    try:
        ist = zoneinfo.ZoneInfo("Asia/Kolkata")
    except Exception:
        import pytz
        ist = pytz.timezone("Asia/Kolkata")
    now = dt.datetime.now(ist)
    feat["feat_hour"] = now.hour
    feat["feat_minutes_since_open"] = (now.hour-9)*60+now.minute-15
    feat["feat_day_of_week"] = now.weekday()

    try:
        a20v = AverageTrueRange(h,l,c,20).average_true_range().iloc[-1]
        feat["feat_volatility"] = float(a20v/c.iloc[-1]*100)
    except: feat["feat_volatility"] = 0.5
    feat["feat_trend_strength"] = feat.get("feat_adx",20)

    try:
        e50 = c.ewm(span=50).mean().iloc[-1]
        feat["feat_futures_premium_proxy"] = float((c.iloc[-1]-e50)/c.iloc[-1]*100)
        e50_6 = c.ewm(span=50).mean().iloc[-7]
        pp = float((c.iloc[-7]-e50_6)/c.iloc[-7]*100)
        feat["feat_premium_change_rate"] = feat["feat_futures_premium_proxy"]-pp
    except: feat["feat_futures_premium_proxy"]=feat["feat_premium_change_rate"]=0

    # India VIX features
    if vix_closes and len(vix_closes) >= 2:
        vix_s = pd.Series(vix_closes)
        vix_now = float(vix_s.iloc[-1])
        feat["feat_vix_level"] = vix_now
        feat["feat_vix_change"] = float(vix_s.pct_change().iloc[-1] * 100) if len(vix_s) > 1 else 0.0
        avg20 = float(vix_s.rolling(20).mean().iloc[-1]) if len(vix_s) >= 20 else float(vix_s.mean())
        feat["feat_vix_vs_avg"] = ((vix_now - avg20) / avg20 * 100) if avg20 > 0 else 0.0
        feat["feat_vix_regime"] = 0.0 if vix_now < 13 else (1.0 if vix_now < 20 else (2.0 if vix_now < 30 else 3.0))
    else:
        feat["feat_vix_level"] = 16.0
        feat["feat_vix_change"] = 0.0
        feat["feat_vix_vs_avg"] = 0.0
        feat["feat_vix_regime"] = 1.0

    # NEW: Momentum continuity features (must match train_multitf.py FEATURE_COLUMNS order)
    try:
        ret = c.pct_change()
        ret_pos = (ret > 0).astype(int)
        consec_up_series = ret_pos.groupby((ret_pos != ret_pos.shift()).cumsum()).cumsum() * ret_pos
        feat["feat_consec_up"] = float(consec_up_series.iloc[-1])
        ret_neg = (ret < 0).astype(int)
        consec_dn_series = ret_neg.groupby((ret_neg != ret_neg.shift()).cumsum()).cumsum() * ret_neg
        feat["feat_consec_down"] = float(consec_dn_series.iloc[-1])
    except: feat["feat_consec_up"] = feat["feat_consec_down"] = 0

    try:
        now_h = feat["feat_hour"]
        now_m = feat["feat_minutes_since_open"] + 9 * 60 + 15  # reverse back to abs minute
        market_open_min = 9 * 60 + 15
        feat["feat_session_position"] = max(0.0, min(1.0, (now_h * 60 + (now_m % 60) - market_open_min) / 375))
    except: feat["feat_session_position"] = 0.5

    try:
        ema9_series = EMAIndicator(c, 9).ema_indicator()
        ema9_dir = ema9_series.diff().map(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        rsi_series = RSIIndicator(c, 14).rsi()
        rsi_dir = rsi_series.diff().map(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        feat["feat_momentum_divergence"] = float(ema9_dir.iloc[-1] != rsi_dir.iloc[-1])
    except: feat["feat_momentum_divergence"] = 0

    # Ensure all columns exist based on training expectations
    X = np.array([[feat.get(k,0) for k in feature_cols]])
    X = np.nan_to_num(X)
    return X, df

def _clean_bars(closes, highs, lows, opens, volumes):
    """Filter out bars where any OHLC value is None/NaN."""
    clean = []
    for i in range(len(closes)):
        c = closes[i]
        h = highs[i]
        l = lows[i]
        o = opens[i] if i < len(opens) else c
        v = volumes[i] if i < len(volumes) else 1
        if c is None or h is None or l is None or o is None:
            continue
        if v is None:
            v = 1
        clean.append((float(c), float(h), float(l), float(o), float(v)))
    return clean

@app.get("/predict")
async def predict():
    try:
        if _rolling_xgb is None:
            return {"error": "rolling model not loaded — check /app/models/nifty_rolling_model.pkl"}
        if _meta is None:
            return {"error": "metadata not loaded — check /app/models/model_metadata_5m.json"}

        raw, raw_bank, vix_closes = await asyncio.gather(
            _fetch_1m("%5ENSEI"), _fetch_1m("%5ENSEBANK"), _fetch_vix()
        )

        if "chart" not in raw or not raw["chart"].get("result"):
            return {"error": "Yahoo Finance returned no Nifty data"}

        result = raw["chart"]["result"][0]
        ts = result.get("timestamp", [])
        q = result["indicators"]["quote"][0]

        bars = _clean_bars(
            q.get("close", []),
            q.get("high", []),
            q.get("low", []),
            q.get("open", q.get("close", [])),
            q.get("volume", [1] * len(ts))
        )

        if len(bars) < 2:
            return {"error": f"insufficient bars from Yahoo: {len(bars)} (need 2+)"}

        X, df_rolling = _extract_features(bars, _meta["feature_columns"], vix_closes=vix_closes)
        if X is None:
            return {"error": "insufficient rolling data for feature extraction"}

        # Rolling model (stable signal — conservative, anti-whipsaw)
        rolling_pred = int(_rolling_xgb.predict(X)[0])
        rolling_probs = _rolling_xgb.predict_proba(X)[0].tolist()

        # Direction model (5m scalp trigger — more reactive)
        dir_pred, dir_probs = rolling_pred, rolling_probs
        ensemble_mode = False
        if _direction_xgb is not None:
            try:
                dir_pred = int(_direction_xgb.predict(X)[0])
                dir_probs = _direction_xgb.predict_proba(X)[0].tolist()
                ensemble_mode = True
            except Exception as de:
                print(f"Direction model prediction error: {de}")

        # OLD 1h direction model (trend bias — 6-hour prediction)
        old_dir_pred, old_dir_probs = None, None
        if _old_direction_xgb is not None and _old_meta is not None:
            try:
                X_old, _ = _extract_features(bars, _old_meta["feature_columns"])
                if X_old is not None:
                    old_dir_pred = int(_old_direction_xgb.predict(X_old)[0])
                    old_dir_probs = _old_direction_xgb.predict_proba(X_old)[0].tolist()
            except Exception as ode:
                print(f"Old direction model prediction error: {ode}")

        # Ensemble: average probabilities from both models when available
        if ensemble_mode:
            probs = [(r + d) / 2 for r, d in zip(rolling_probs, dir_probs)]
            pred = int(np.argmax(probs))
        else:
            pred = rolling_pred
            probs = rolling_probs

        cross_pred, cross_probs = None, []
        if _cross_xgb is not None and "chart" in raw_bank and raw_bank["chart"].get("result"):
            try:
                rb = raw_bank["chart"]["result"][0]
                qb = rb["indicators"]["quote"][0]
                bbars = _clean_bars(
                    qb.get("close", []),
                    qb.get("high", []),
                    qb.get("low", []),
                    qb.get("open", qb.get("close", [])),
                    qb.get("volume", [1] * len(rb.get("timestamp", [])))
                )

                if len(bbars) >= 5:
                    bank_roll = build_rolling_bar(bbars[-5:])
                    if bank_roll:
                        bc, bh, bl, bo = bank_roll[0], bank_roll[1], bank_roll[2], bank_roll[3]

                        if bo > 0 and bc > 0 and df_rolling.Open.iloc[-1] > 0:
                            bank_ret = (bc - bo) / bo * 100
                            nifty_ret = (df_rolling.Close.iloc[-1] - df_rolling.Open.iloc[-1]) / df_rolling.Open.iloc[-1] * 100

                            feat_bank_spread = bank_ret - nifty_ret
                            feat_bank_volatility = (bh - bl) / bc * 100

                            X_cross = np.append(X[0], [feat_bank_spread, feat_bank_volatility]).reshape(1, -1)

                            cross_pred = int(_cross_xgb.predict(X_cross)[0])
                            cross_probs = _cross_xgb.predict_proba(X_cross)[0].tolist()
            except Exception as ce:
                import traceback
                print(f"Cross-asset prediction error: {ce}\n{traceback.format_exc()}")

        def _parse_acc(meta_dict):
            if not meta_dict: return 0.0
            a = meta_dict.get("accuracy", 0)
            return a if a > 1 else a * 100

        model_acc = _parse_acc(_meta)
        old_model_acc = _parse_acc(_old_meta)

        resp = {
            "prediction": pred,
            "probs": probs,
            "xgb_probs": rolling_probs,
            "lstm_probs": dir_probs,
            "cross_asset_prediction": cross_pred if cross_pred is not None else pred,
            "cross_asset_probs": cross_probs if cross_probs else probs,
            "ensemble_mode": ensemble_mode,
            "model_accuracy": round(model_acc, 2),
            "models": {
                "rolling": {
                    "prediction": rolling_pred,
                    "probs": rolling_probs,
                    "label": "Rolling (Stable Signal)",
                    "accuracy": round(_parse_acc(_meta), 2),
                },
                "direction": {
                    "prediction": dir_pred,
                    "probs": dir_probs,
                    "label": "Direction (5m Scalp)",
                    "accuracy": round(model_acc, 2) if ensemble_mode else 0,
                },
                "cross_asset": {
                    "prediction": cross_pred if cross_pred is not None else pred,
                    "probs": cross_probs if cross_probs else [0, 0, 0],
                    "label": "Cross-Asset (BankNifty)",
                    "accuracy": round(_parse_acc(_meta), 2),
                },
            },
        }

        if old_dir_pred is not None:
            resp["models"]["old_direction"] = {
                "prediction": old_dir_pred,
                "probs": old_dir_probs,
                "label": "Old Direction (1h Trend)",
                "accuracy": round(old_model_acc, 2),
            }

        return resp
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}

def _build_scalper_features(bars_1m: list, vix_closes: list, sector_data: dict, feat_cols: list) -> np.ndarray | None:
    """
    Build the 42-feature sequence matrix for the 3-minute scalper LSTM.
    bars_1m: list of (close, high, low, open, volume) tuples, 1-minute resolution
    Returns: (seq_len, n_features) numpy array, or None if insufficient data
    """
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.trend import ADXIndicator, MACD, EMAIndicator
    from ta.volatility import AverageTrueRange, BollingerBands

    SEQ_LEN = _scalper_meta["seq_len"]
    if len(bars_1m) < 2:
        return None

    # Build DataFrame from raw 1m bars
    df = pd.DataFrame(bars_1m, columns=["Close", "High", "Low", "Open", "Volume"])
    df = df.astype(float)
    close = df["Close"]; high = df["High"]; low = df["Low"]

    # ── Feature matrix: one row per 1m bar ──
    feat_df = pd.DataFrame(index=df.index)

    # Returns
    feat_df["f_ret1"]  = close.pct_change(1) * 100
    feat_df["f_ret2"]  = close.pct_change(2) * 100
    feat_df["f_ret3"]  = close.pct_change(3) * 100
    feat_df["f_ret5"]  = close.pct_change(5) * 100
    feat_df["f_ret10"] = close.pct_change(10) * 100

    # Candle shape
    feat_df["f_body_pct"]   = ((close - df["Open"]) / df["Open"] * 100).fillna(0)
    feat_df["f_upper_wick"] = ((high - close.clip(lower=df["Open"])) / df["Open"] * 100).fillna(0)
    feat_df["f_lower_wick"] = ((close.clip(upper=df["Open"]) - low) / df["Open"] * 100).fillna(0)
    feat_df["f_hl_range"]   = ((high - low) / close * 100).fillna(0)

    # RSI
    try:
        feat_df["f_rsi14"]    = RSIIndicator(close, 14).rsi()
        feat_df["f_rsi7"]     = RSIIndicator(close, 7).rsi()
        feat_df["f_rsi_delta"]= feat_df["f_rsi14"].diff(1)
    except:
        feat_df["f_rsi14"] = feat_df["f_rsi7"] = 50.0
        feat_df["f_rsi_delta"] = 0.0

    # MACD
    try:
        macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
        feat_df["f_macd_hist"]  = macd.macd_diff()
        feat_df["f_macd_delta"] = feat_df["f_macd_hist"].diff(1)
    except:
        feat_df["f_macd_hist"] = feat_df["f_macd_delta"] = 0.0

    # EMA spreads
    try:
        ema5  = EMAIndicator(close, 5).ema_indicator()
        ema9  = EMAIndicator(close, 9).ema_indicator()
        ema21 = EMAIndicator(close, 21).ema_indicator()
        feat_df["f_ema5_9_spread"]  = (ema5 - ema9) / close * 100
        feat_df["f_ema9_21_spread"] = (ema9 - ema21) / close * 100
        feat_df["f_price_vs_ema9"]  = (close - ema9) / close * 100
        feat_df["f_price_vs_ema21"] = (close - ema21) / close * 100
    except:
        feat_df["f_ema5_9_spread"] = feat_df["f_ema9_21_spread"] = 0.0
        feat_df["f_price_vs_ema9"] = feat_df["f_price_vs_ema21"] = 0.0

    # ATR
    try:
        atr = AverageTrueRange(high, low, close, 14).average_true_range()
        feat_df["f_atr_pct"]    = (atr / close * 100)
        feat_df["f_atr_move"]   = ((close - close.shift(1)) / atr).fillna(0)
        atr_ma50 = atr.rolling(50).mean()
        feat_df["f_atr_regime"] = (atr / atr_ma50).fillna(1.0)
    except:
        feat_df["f_atr_pct"] = feat_df["f_atr_move"] = feat_df["f_atr_regime"] = 1.0

    # Bollinger
    try:
        bb = BollingerBands(close, 20, 2)
        bb_range = bb.bollinger_hband() - bb.bollinger_lband()
        feat_df["f_bb_pos"]   = np.where(bb_range > 0, (close - bb.bollinger_lband()) / bb_range, 0.5)
        feat_df["f_bb_width"] = bb_range / close * 100
    except:
        feat_df["f_bb_pos"] = 0.5; feat_df["f_bb_width"] = 1.0

    # Stochastic
    try:
        stoch = StochasticOscillator(high, low, close, 14, 3)
        feat_df["f_stoch_k"] = stoch.stoch()
        feat_df["f_stoch_d"] = stoch.stoch_signal()
    except:
        feat_df["f_stoch_k"] = feat_df["f_stoch_d"] = 50.0

    # ADX
    try:
        adx = ADXIndicator(high, low, close, 14)
        feat_df["f_adx"]     = adx.adx()
        feat_df["f_di_diff"] = adx.adx_pos() - adx.adx_neg()
    except:
        feat_df["f_adx"] = 25.0; feat_df["f_di_diff"] = 0.0

    # Momentum streaks
    try:
        ret_sign = np.sign(close.pct_change())
        up = (ret_sign > 0).astype(int)
        dn = (ret_sign < 0).astype(int)
        feat_df["f_consec_up"]   = up.groupby((up != up.shift()).cumsum()).cumsum() * up
        feat_df["f_consec_down"] = dn.groupby((dn != dn.shift()).cumsum()).cumsum() * dn
    except:
        feat_df["f_consec_up"] = feat_df["f_consec_down"] = 0.0

    # Session position — use bar index as proxy (bar 0 = open, bar 374 = close)
    n = len(df)
    feat_df["f_session_pos"] = pd.Series(
        [(max(0, min(374, n - (n - i)))) / 374 for i in range(n)],
        index=df.index
    )

    # VIX
    if vix_closes and len(vix_closes) >= 2:
        vix_s = pd.Series(vix_closes[-n:] if len(vix_closes) >= n else vix_closes)
        # Pad/align to same length as df
        vix_aligned = pd.Series(vix_s.values, index=range(len(vix_s))).reindex(range(n)).ffill().bfill()
        vix_aligned = vix_aligned.fillna(16.0)
        vix_ma20 = vix_aligned.rolling(20).mean().fillna(vix_aligned.mean())
        feat_df["f_vix"]        = vix_aligned.values
        feat_df["f_vix_chg"]    = vix_aligned.pct_change(1).fillna(0) * 100
        feat_df["f_vix_vs_avg"] = ((vix_aligned - vix_ma20) / vix_ma20.replace(0, 1) * 100).fillna(0)
        feat_df["f_vix_regime"] = pd.cut(vix_aligned, bins=[0,13,20,30,10000],
                                          labels=[0,1,2,3]).astype(float).fillna(1.0).values
    else:
        feat_df["f_vix"] = 16.0; feat_df["f_vix_chg"] = 0.0
        feat_df["f_vix_vs_avg"] = 0.0; feat_df["f_vix_regime"] = 1.0

    # Sector relative returns + breadth
    sec_keys = _scalper_meta.get("sector_keys", [])
    breadth_cols = []
    for key in sec_keys:
        col = f"f_sec_{key}_rel"
        if key in sector_data and len(sector_data[key]) >= 2:
            sec_closes = pd.Series(sector_data[key])
            sec_ret = sec_closes.pct_change(1).fillna(0) * 100
            # Align to df length
            sec_ret_aligned = sec_ret.reindex(range(n)).ffill().bfill().fillna(0)
            nifty_ret = feat_df["f_ret1"].fillna(0)
            rel = (sec_ret_aligned.values - nifty_ret.values)
            feat_df[col] = rel
            breadth_cols.append(col)
            feat_df[f"_adv_{key}"] = (sec_ret_aligned.values > 0).astype(float)
        else:
            feat_df[col] = 0.0
            feat_df[f"_adv_{key}"] = 0.5

    adv_cols = [f"_adv_{k}" for k in sec_keys]
    feat_df["f_breadth_score"] = feat_df[adv_cols].sum(axis=1) if adv_cols else 0.0

    # Align columns to training feature order and fill NaN
    X_mat = feat_df[feat_cols].values.astype(np.float32)
    X_mat = np.nan_to_num(X_mat, nan=0.0, posinf=0.0, neginf=0.0)

    # Scale
    X_scaled = _scalper_scaler.transform(X_mat)

    # Build sequence: take last SEQ_LEN rows
    if len(X_scaled) < SEQ_LEN:
        # Pad start with first row
        pad = np.tile(X_scaled[0], (SEQ_LEN - len(X_scaled), 1))
        X_scaled = np.vstack([pad, X_scaled])

    seq = X_scaled[-SEQ_LEN:][np.newaxis, :, :]  # shape (1, SEQ_LEN, n_features)
    return seq.astype(np.float32)


@app.get("/predict-scalper")
async def predict_scalper():
    """
    3-Minute Scalper LSTM endpoint.
    Fetches live 1m data, sector closes, and VIX, then runs the scalper LSTM.
    Returns: signal (UP/DOWN/SIDEWAYS), probs [P_side, P_up, P_down], confidence.
    """
    try:
        if _scalper_lstm is None or _scalper_scaler is None or _scalper_meta is None:
            return {"error": "scalper model not loaded — run train_scalper_lstm.py first"}

        feat_cols  = _scalper_meta["feature_columns"]
        sec_keys   = _scalper_meta.get("sector_keys", [])

        # Fetch all data in parallel: Nifty 1m + each sector + VIX
        sector_tickers = {
            "bank": "%5ENSEBANK",
            "it":   "^CNXIT",
            "fin":  "NIFTY_FIN_SERVICE.NS",
            "auto": "^CNXAUTO",
            "fmcg": "^CNXFMCG",
        }

        async def fetch_sector(ticker):
            try:
                url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
                timeout = aiohttp.ClientTimeout(total=8)
                async with aiohttp.ClientSession(timeout=timeout) as s:
                    async with s.get(url, headers=_YAHOO_HEADERS) as r:
                        if r.status != 200: return []
                        data = await r.json(content_type=None)
                res = data.get("chart", {}).get("result", [])
                if not res: return []
                q = res[0]["indicators"]["quote"][0]
                return [v for v in q.get("close", []) if v is not None]
            except:
                return []

        tasks = [_fetch_1m("%5ENSEI", "1d"), _fetch_vix()]
        for key in sec_keys:
            ticker = sector_tickers.get(key, "")
            if ticker:
                tasks.append(fetch_sector(ticker))
            else:
                tasks.append(asyncio.coroutine(lambda: [])())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        raw_nifty = results[0] if not isinstance(results[0], Exception) else {}
        vix_closes = results[1] if not isinstance(results[1], Exception) else []
        sector_data = {}
        for i, key in enumerate(sec_keys):
            val = results[2 + i]
            sector_data[key] = val if not isinstance(val, Exception) else []

        if "chart" not in raw_nifty or not raw_nifty["chart"].get("result"):
            return {"error": "Yahoo Finance returned no Nifty 1m data"}

        result = raw_nifty["chart"]["result"][0]
        q = result["indicators"]["quote"][0]
        bars_1m = _clean_bars(
            q.get("close", []), q.get("high", []), q.get("low", []),
            q.get("open", q.get("close", [])),
            q.get("volume", [1] * len(result.get("timestamp", [])))
        )

        if len(bars_1m) < 2:
            return {"error": f"insufficient 1m bars: {len(bars_1m)}"}

        seq = _build_scalper_features(bars_1m, vix_closes, sector_data, feat_cols)
        if seq is None:
            return {"error": "feature extraction failed"}

        probs = _scalper_lstm.predict(seq, verbose=0)[0].tolist()  # [P_side, P_up, P_dn]
        pred_idx = int(np.argmax(probs))
        classes = _scalper_meta.get("classes", ["SIDEWAYS", "UP", "DOWN"])
        pred_label = classes[pred_idx]
        confidence = round(probs[pred_idx] * 100, 1)

        # Map to trading signal
        signal = "NO TRADE"
        if pred_label == "UP" and confidence > 40:
            signal = "BUY CE"
        elif pred_label == "DOWN" and confidence > 45:  # higher bar for bearish
            signal = "BUY PE"

        return {
            "signal":          signal,
            "prediction":      pred_label,
            "confidence":      confidence,
            "probs": {
                "sideways": round(probs[0] * 100, 1),
                "up":       round(probs[1] * 100, 1),
                "down":     round(probs[2] * 100, 1),
            },
            "horizon_minutes": _scalper_meta["forward_bars"],
            "seq_len_used":    _scalper_meta["seq_len"],
            "model_accuracy":  _scalper_meta.get("accuracy", 0),
            "bars_available":  len(bars_1m),
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}


# ─── Overnight Nifty (v3 stacked + regression) ────────────────────────────────
import sys as _sys
_OVERNIGHT_DIR = os.path.join(ML_DIR, "overnight_nifty")
if _OVERNIGHT_DIR not in _sys.path:
    _sys.path.insert(0, _OVERNIGHT_DIR)

_overnight_loaded = False

# Backfill state — protects against concurrent fetches and powers the UI status endpoint
import threading as _threading
from datetime import datetime as _datetime
_OVERNIGHT_RAW_PARQUET = os.path.join(_OVERNIGHT_DIR, "data", "overnight_raw.parquet")
_overnight_fetch_lock = _threading.Lock()
_overnight_fetch_in_progress = False
_overnight_fetch_started_at = None
_overnight_last_fetch_status = None  # "ok" | "failed: <msg>" | None
_overnight_last_fetch_at = None


def _try_load_overnight():
    """Lazy-load overnight model on first use; returns the predict module or None."""
    global _overnight_loaded
    try:
        import predict_overnight as po
        po.load_models()
        _overnight_loaded = True
        return po
    except Exception as e:
        print(f"Overnight Nifty model not loaded: {e}")
        return None


def _do_overnight_fetch_and_predict(predict_after: bool = True):
    """Refresh the overnight raw parquet (10y) and optionally re-run the prediction.
    Idempotent — exits immediately if a fetch is already in progress.
    Safe to call from APScheduler, /refresh_overnight_data, or startup bootstrap.
    """
    global _overnight_fetch_in_progress, _overnight_fetch_started_at
    global _overnight_last_fetch_status, _overnight_last_fetch_at

    with _overnight_fetch_lock:
        if _overnight_fetch_in_progress:
            print("[overnight-fetch] skipped — fetch already in progress")
            return
        _overnight_fetch_in_progress = True
        _overnight_fetch_started_at = _datetime.utcnow().isoformat() + "Z"

    try:
        import data_fetcher as df_mod
        print("[overnight-fetch] downloading raw data (10y, ~3 min)…")
        df_mod.save(df_mod.fetch_all(years=10))
        _overnight_last_fetch_status = "ok"
        _overnight_last_fetch_at = _datetime.utcnow().isoformat() + "Z"
        print("[overnight-fetch] raw data refresh complete")

        if predict_after:
            po = _try_load_overnight()
            if po is None:
                print("[overnight-fetch] model not loaded — skipping prediction")
                return
            try:
                result = po.predict_and_log()
                print(f"[overnight-fetch] prediction generated: dir={result.get('direction')} "
                      f"conf={result.get('direction_confidence')} target={result.get('target_date')}")
            except Exception as e:
                print(f"[overnight-fetch] predict failed after fetch: {e}")
    except Exception as e:
        import traceback
        _overnight_last_fetch_status = f"failed: {e}"
        _overnight_last_fetch_at = _datetime.utcnow().isoformat() + "Z"
        print(f"[overnight-fetch] FAILED: {e}\n{traceback.format_exc()}")
    finally:
        with _overnight_fetch_lock:
            _overnight_fetch_in_progress = False


@app.get("/predict_nifty_overnight")
async def predict_nifty_overnight():
    """v3 stacked direction + regression close prediction for the next NSE session.
    Returns the latest cached prediction from the prediction log if today's row
    is already there; otherwise runs a fresh prediction."""
    if not os.path.exists(_OVERNIGHT_RAW_PARQUET):
        return {
            "error": "data_missing",
            "error_code": "data_missing",
            "message": "Overnight raw data not available yet. Trigger a backfill from the UI or wait for the 03:30 IST cron.",
            "fetch_in_progress": _overnight_fetch_in_progress,
        }
    po = _try_load_overnight()
    if po is None:
        return {
            "error": "model_not_loaded",
            "error_code": "model_not_loaded",
            "message": "Overnight model artifacts missing — check the deployment.",
        }
    try:
        return po.predict_and_log()
    except FileNotFoundError as e:
        return {
            "error": "data_missing",
            "error_code": "data_missing",
            "message": str(e),
            "fetch_in_progress": _overnight_fetch_in_progress,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}


@app.post("/refresh_overnight_data")
def refresh_overnight_data():
    """Trigger a background refresh of the overnight raw parquet + a fresh prediction.
    Returns immediately. Poll /overnight_data_status to track progress."""
    if _overnight_fetch_in_progress:
        return {
            "started": False,
            "fetch_in_progress": True,
            "message": "fetch already running",
            "started_at": _overnight_fetch_started_at,
        }
    _threading.Thread(target=_do_overnight_fetch_and_predict, daemon=True).start()
    return {"started": True, "fetch_in_progress": True}


@app.get("/overnight_data_status")
def overnight_data_status():
    """UI-facing state of the overnight raw parquet + fetch lifecycle."""
    exists = os.path.exists(_OVERNIGHT_RAW_PARQUET)
    last_modified = None
    age_hours = None
    if exists:
        mtime = os.path.getmtime(_OVERNIGHT_RAW_PARQUET)
        last_modified = _datetime.fromtimestamp(mtime).isoformat()
        age_hours = round((time.time() - mtime) / 3600, 1)
    return {
        "exists": exists,
        "last_modified": last_modified,
        "age_hours": age_hours,
        "fetch_in_progress": _overnight_fetch_in_progress,
        "fetch_started_at": _overnight_fetch_started_at,
        "last_fetch_status": _overnight_last_fetch_status,
        "last_fetch_at": _overnight_last_fetch_at,
    }


@app.get("/predict_nifty_overnight/log")
async def predict_nifty_overnight_log(limit: int = 30):
    """Return the last `limit` rows of overnight_predictions.csv (latest first)."""
    log_path = os.path.join(_OVERNIGHT_DIR, "data", "overnight_predictions.csv")
    if not os.path.exists(log_path):
        return {"error": "no prediction log yet", "rows": []}
    try:
        df = pd.read_csv(log_path).tail(int(limit))
        # Replace NaN with None — strict JSON doesn't allow NaN, and pending
        # actual_close/abs_error/direction_correct are legitimately NaN.
        df = df.astype(object).where(pd.notna(df), None)
        return {"rows": df.to_dict("records"), "n": len(df)}
    except Exception as e:
        return {"error": str(e), "rows": []}


# ─── APScheduler: daily refresh + predict + backfill ──────────────────────────
_overnight_scheduler = None

def _overnight_refresh_and_predict():
    """Cron entry point — delegates to the shared lock-protected helper."""
    _do_overnight_fetch_and_predict(predict_after=True)


def _overnight_backfill_actuals():
    """Refetch raw data (so today's NSE close is captured) and backfill the CSV."""
    try:
        import data_fetcher as df_mod
        df_mod.save(df_mod.fetch_all(years=10))
    except Exception as e:
        print(f"[cron] data refresh (backfill) failed: {e}")
    try:
        po = _try_load_overnight()
        if po is None:
            return
        n = po.backfill_actuals()
        print(f"[cron] backfilled {n} rows of actual closes")
    except Exception as e:
        print(f"[cron] backfill failed: {e}")


@app.on_event("startup")
def _start_overnight_scheduler():
    """Eager-load the overnight model and schedule:
      • 03:30 IST daily — refresh data + run prediction (after US close, during Asia open)
      • 16:00 IST daily — backfill actual closes (NSE closes 15:30 IST)
    Disabled if SPECTRE_DISABLE_SCHEDULER=1 in env."""
    global _overnight_scheduler
    _try_load_overnight()  # eager load so /health reflects state immediately

    # Auto-bootstrap: if the parquet doesn't exist yet (fresh deploy / new volume),
    # kick off a background fetch so the user doesn't have to wait for 03:30 IST.
    if not os.path.exists(_OVERNIGHT_RAW_PARQUET):
        print("[startup] overnight parquet missing — kicking off background backfill")
        _threading.Thread(target=_do_overnight_fetch_and_predict, daemon=True).start()

    if os.environ.get("SPECTRE_DISABLE_SCHEDULER") == "1":
        print("Overnight scheduler disabled via SPECTRE_DISABLE_SCHEDULER=1")
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        try:
            ist = zoneinfo.ZoneInfo("Asia/Kolkata")
        except Exception:
            import pytz
            ist = pytz.timezone("Asia/Kolkata")
        sched = BackgroundScheduler(timezone=ist)
        sched.add_job(_overnight_refresh_and_predict,
                      CronTrigger(hour=3, minute=30, timezone=ist),
                      id="overnight_predict", replace_existing=True,
                      misfire_grace_time=3600)
        sched.add_job(_overnight_backfill_actuals,
                      CronTrigger(hour=16, minute=0, timezone=ist),
                      id="overnight_backfill", replace_existing=True,
                      misfire_grace_time=3600)
        sched.start()
        _overnight_scheduler = sched
        print("Overnight Nifty scheduler started — 03:30 IST predict, 16:00 IST backfill")
    except Exception as e:
        print(f"Overnight scheduler not started: {e}")


@app.get("/health")
def health(): return {"status":"ok","rolling_model_loaded":_rolling_xgb is not None, "cross_model_loaded": _cross_xgb is not None, "old_model_loaded": _old_direction_xgb is not None, "scalper_loaded": _scalper_lstm is not None, "overnight_loaded": _overnight_loaded, "overnight_scheduler_running": _overnight_scheduler is not None and _overnight_scheduler.running if _overnight_scheduler else False}

@app.get("/morning-predict")
async def morning_predict():
    import datetime as dt
    try:
        try:
            ist = zoneinfo.ZoneInfo("Asia/Kolkata")
        except Exception:
            import pytz
            ist = pytz.timezone("Asia/Kolkata")
        now = dt.datetime.now(ist)

        if now.hour != 9 or now.minute < 5 or now.minute > 25:
            return {"error": "morning signal only available 09:05-09:25 IST", "skip": True}

        if _old_direction_xgb is None or _old_meta is None:
            return {"error": "old direction model not loaded", "skip": True}
        if _meta is None:
            return {"error": "metadata not loaded", "skip": True}

        raw_1m, raw_5m = await asyncio.gather(
            _fetch_1m("%5ENSEI", "2d"),
            _fetch_5m("%5ENSEI", "5d"),
        )

        if "chart" not in raw_1m or not raw_1m["chart"].get("result"):
            return {"error": "Yahoo Finance returned no Nifty 1m data", "skip": True}

        result = raw_1m["chart"]["result"][0]
        ts = result.get("timestamp", [])
        q = result["indicators"]["quote"][0]

        bars = _clean_bars(
            q.get("close", []),
            q.get("high", []),
            q.get("low", []),
            q.get("open", q.get("close", [])),
            q.get("volume", [1] * len(ts))
        )

        if len(bars) < 55:
            return {"error": f"insufficient 1m bars: {len(bars)} (need 55+)", "skip": True}

        X, df_rolling = _extract_features(bars, _old_meta["feature_columns"])
        if X is None:
            return {"error": "insufficient rolling data for feature extraction", "skip": True}

        pred = int(_old_direction_xgb.predict(X)[0])
        probs = _old_direction_xgb.predict_proba(X)[0].tolist()

        labels = ["DOWN", "SIDEWAYS", "UP"]
        top_idx = int(np.argmax(probs))
        top_prob = probs[top_idx]
        second_prob = sorted(probs)[-2]
        gap = top_prob - second_prob
        conf = top_prob * 100

        ltp = df_rolling.Close.iloc[-1]

        gap_pct = 0.0
        prev_close = 0.0
        today_open = 0.0
        closes_5m = []

        if "chart" in raw_5m and raw_5m["chart"].get("result"):
            r5 = raw_5m["chart"]["result"][0]
            q5 = r5["indicators"]["quote"][0]
            closes_5m = [c for c in q5.get("close", []) if c is not None and c > 0]
            opens_5m = [o for o in q5.get("open", []) if o is not None and o > 0]
            if len(closes_5m) >= 2:
                prev_close = closes_5m[-2] if len(closes_5m) >= 2 else closes_5m[-1]
                today_open = df_rolling.Open.iloc[-1] if len(df_rolling) > 0 else 0
                if prev_close > 0 and today_open > 0:
                    gap_pct = round((today_open - prev_close) / prev_close * 100, 3)

        gap_type = "FLAT"
        gap_filter = "OK"
        gap_severity = "none"
        GAP_LARGE = 0.8
        GAP_MODERATE = 0.4

        if gap_pct > GAP_LARGE:
            gap_type = "LARGE GAP UP"
            gap_severity = "high"
            gap_filter = "SKIP"
        elif gap_pct > GAP_MODERATE:
            gap_type = "MODERATE GAP UP"
            gap_severity = "medium"
            gap_filter = "CAUTION"
        elif gap_pct < -GAP_LARGE:
            gap_type = "LARGE GAP DOWN"
            gap_severity = "high"
            gap_filter = "SKIP"
        elif gap_pct < -GAP_MODERATE:
            gap_type = "MODERATE GAP DOWN"
            gap_severity = "medium"
            gap_filter = "CAUTION"

        prev_day_trend = "NEUTRAL"
        if len(closes_5m) >= 50:
            last_50 = closes_5m[-50:]
            prev_day_close = last_50[0]
            prev_day_end = last_50[-2] if len(last_50) >= 2 else last_50[-1]
            if prev_day_close > 0:
                chg = (prev_day_end - prev_day_close) / prev_day_close * 100
                if chg > 0.3:
                    prev_day_trend = "BULLISH"
                elif chg < -0.3:
                    prev_day_trend = "BEARISH"

        raw_signal = "NO TRADE"
        opt_type = "-"
        if labels[pred] == "UP" and conf > 38:
            raw_signal = "BUY CE"
            opt_type = "CE"
        elif labels[pred] == "DOWN" and conf > 38:
            raw_signal = "BUY PE"
            opt_type = "PE"

        if gap_filter == "SKIP" and conf < 55:
            raw_signal = "NO TRADE (GAP SKIP)"
            opt_type = "-"

        if gap_filter == "CAUTION":
            raw_signal = f"{raw_signal} (CAUTION)"

        filtered_conf = conf
        if gap_severity == "high":
            filtered_conf = conf * 0.5
        elif gap_severity == "medium":
            filtered_conf = conf * 0.75

        return {
            "prediction": labels[pred],
            "confidence": round(conf, 1),
            "filtered_confidence": round(filtered_conf, 1),
            "probs": {k: round(v * 100, 1) for k, v in zip(labels, probs)},
            "prob_gap": round(gap * 100, 1),
            "raw_signal": raw_signal,
            "option_type": opt_type,
            "nifty_spot": round(ltp, 2),
            "prev_day_close": round(prev_close, 2),
            "today_open": round(today_open, 2),
            "gap_pct": gap_pct,
            "gap_type": gap_type,
            "gap_severity": gap_severity,
            "gap_filter": gap_filter,
            "prev_day_trend": prev_day_trend,
            "model_accuracy": round(_old_meta.get("accuracy", 0) * 100, 1),
            "generated_at": now.strftime("%H:%M:%S IST"),
            "valid_for_minutes": 5,
            "features_used": len(_old_meta.get("feature_columns", [])),
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}
