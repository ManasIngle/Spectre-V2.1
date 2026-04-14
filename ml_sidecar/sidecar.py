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

@app.on_event("startup")
def startup_load():
    _load()

import aiohttp, asyncio, pandas as pd

async def _fetch_1m(ticker="%5ENSEI", days="1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range={days}"
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, headers={"User-Agent":"Mozilla/5.0"}) as r:
            return await r.json()

async def _fetch_5m(ticker="%5ENSEI", days="5d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range={days}"
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, headers={"User-Agent":"Mozilla/5.0"}) as r:
            return await r.json()

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
    Takes the last 5 1-minute candles and mathematically crushes them 
    into a single 5-minute rolling structure.
    bars shape: [Close, High, Low, Open, Volume]
    """
    if len(bars) < 5: return None
    
    recent_5 = np.array(bars[-5:])
    c_ = recent_5[:,0]
    h_ = recent_5[:,1]
    l_ = recent_5[:,2]
    o_ = recent_5[:,3]
    v_ = recent_5[:,4]
    
    roll_o = o_[0]
    roll_h = np.max(h_)
    roll_l = np.min(l_)
    roll_c = c_[-1]
    roll_v = np.sum(v_)
    
    return [roll_c, roll_h, roll_l, roll_o, roll_v]

def _extract_features(bars, feature_cols, vix_closes=None):
    import pandas as pd
    from ta.trend import ADXIndicator, MACD, EMAIndicator
    from ta.momentum import RSIIndicator
    from ta.volatility import BollingerBands, AverageTrueRange

    # We must construct a DataFrame out of sliding rolling bars over the 1m history
    # so the indicators (like 14-period RSI) calculate correctly against rolling structures.
    rolling_history = []
    for i in range(4, len(bars)):
        r = build_rolling_bar(bars[i-4:i+1])
        if r: rolling_history.append(r)
        
    df = pd.DataFrame(rolling_history, columns=["Close","High","Low","Open","Volume"])
    if len(df) < 50: return None, df

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

        if len(bars) < 55:
            return {"error": f"insufficient bars from Yahoo: {len(bars)} (need 55+)"}

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

@app.get("/health")
def health(): return {"status":"ok","rolling_model_loaded":_rolling_xgb is not None, "cross_model_loaded": _cross_xgb is not None, "old_model_loaded": _old_direction_xgb is not None}

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
