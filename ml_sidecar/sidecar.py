"""
Spectre ML Sidecar — lightweight FastAPI server that loads the pkl/keras
models once and serves predictions via HTTP to the Go main server.

Run: uvicorn sidecar:app --port 8001
"""
import os, json, time, numpy as np, joblib
from fastapi import FastAPI

ML_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "ml")

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

_xgb = _meta = _lstm = _scaler = _lstm_meta = None

def _load():
    global _xgb, _meta, _lstm, _scaler, _lstm_meta
    paths = _get_model_paths()
    
    if _xgb is None:
        if not os.path.exists(paths["model"]):
            print(f"Warning: Model not found at {paths['model']}")
            return
            
        _xgb = joblib.load(paths["model"])
        with open(paths["meta"]) as f: _meta = json.load(f)
    if _lstm is None:
        try:
            from tensorflow.keras.models import load_model
            _lstm = load_model(paths["lstm"])
            _scaler = joblib.load(paths["scaler"])
            with open(paths["lstm_meta"]) as f: _lstm_meta = json.load(f)
        except Exception as e:
            print(f"LSTM load failed: {e}")

import aiohttp, asyncio

async def _fetch_5m():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?interval=5m&range=5d"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers={"User-Agent":"Mozilla/5.0"}) as r:
            return await r.json()

def _extract_features(bars, feature_cols):
    """Same feature extraction as trade_signals.py _extract_live_features."""
    import pandas as pd
    from ta.trend import ADXIndicator, MACD, EMAIndicator
    from ta.momentum import RSIIndicator
    from ta.volatility import BollingerBands, AverageTrueRange

    df = pd.DataFrame(bars, columns=["Close","High","Low","Open","Volume"])
    if len(df) < 70: return None

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

    feat.update({"feat_equity_weighted_ret":0,"feat_equity_advance_pct":0,"feat_equity_momentum":0})

    import datetime as dt
    now = dt.datetime.now()
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

    X = np.array([[feat.get(k,0) for k in feature_cols]])
    X = np.nan_to_num(X)
    return X

@app.get("/predict")
async def predict():
    _load()
    try:
        raw = await _fetch_5m()
        result = raw["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
        bars = list(zip(q["close"],q["high"],q["low"],q.get("open",q["close"]),q.get("volume",[1]*len(ts))))

        X = _extract_features(bars, _meta["feature_columns"])
        if X is None:
            return {"error":"insufficient data","prediction":1,"probs":[0.33,0.34,0.33],"ensemble_mode":False}

        xgb_pred = int(_xgb.predict(X)[0])
        xgb_probs = _xgb.predict_proba(X)[0].tolist()

        probs = xgb_probs
        ensemble = False

        if _lstm is not None:
            try:
                seq = np.array(bars[-30:])
                c_ = seq[:,0]; h_=seq[:,1]; l_=seq[:,2]; o_=seq[:,3]; v_=seq[:,4]
                feat = np.column_stack([
                    np.concatenate([[0],np.diff(c_)/np.maximum(c_[:-1],1)*100]),
                    (h_-l_)/np.maximum(c_,1)*100,(c_-o_)/np.maximum(c_,1)*100,
                    (h_-np.maximum(c_,o_))/np.maximum(c_,1)*100,
                    (np.minimum(c_,o_)-l_)/np.maximum(c_,1)*100,
                    np.concatenate([[1],v_[1:]/np.maximum(v_[:-1],1)]),
                    np.where(h_-l_>0,(c_-l_)/(h_-l_),0.5),
                    np.concatenate([[0],(o_[1:]-c_[:-1])/np.maximum(c_[:-1],1)*100]),
                ])
                feat_s = _scaler.transform(feat)
                Xl = feat_s[-30:].reshape(1,30,-1)
                lstm_probs = _lstm.predict(Xl,verbose=0)[0].tolist()
                probs = [0.6*xgb_probs[i]+0.4*lstm_probs[i] for i in range(3)]
                ensemble = True
            except: pass

        pred = int(np.argmax(probs))
        return {
            "prediction": pred,
            "probs": probs,
            "xgb_probs": xgb_probs,
            "lstm_probs": [] if not ensemble else lstm_probs,
            "ensemble_mode": ensemble,
            "model_accuracy": _meta.get("accuracy",0),
        }
    except Exception as e:
        return {"error": str(e), "prediction":1,"probs":[0.33,0.34,0.33],"ensemble_mode":False}

@app.get("/health")
def health(): return {"status":"ok","model_loaded":_xgb is not None}
