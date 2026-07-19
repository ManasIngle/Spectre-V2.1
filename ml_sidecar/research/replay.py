#!/usr/bin/env python3
"""
Step 1 — Offline replay harness + live-log validation.
Faithfully reproduces the live signal pipeline (sidecar.py) using DB data,
validates against system_signals-18July.csv.
"""
import os, sys, json, argparse, sqlite3, time as time_mod, gc
import numpy as np
import pandas as pd
import joblib
import zoneinfo

from ta.trend import ADXIndicator, MACD, EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_DIR = os.path.join(ROOT_DIR, "ml_sidecar", "models")
RESEARCH_DIR = os.path.join(ROOT_DIR, "ml_sidecar", "research")
DATA_DIR = os.path.join(RESEARCH_DIR, "data")
REPORT_DIR = os.path.join(RESEARCH_DIR, "reports")
SIGNALS_CSV = os.path.join(ROOT_DIR, "system_signals-18July.csv")
DB_PATH = "/Users/manasingle/Edge/June/Miequity/archive_2020_smart.db"

RANDOM_SEED = 42
IST = zoneinfo.ZoneInfo("Asia/Kolkata")
VER = "-Rtr14April"

ROLLING_MODEL_PATH = os.path.join(MODEL_DIR, f"nifty_rolling_model{VER}.pkl")
DIRECTION_MODEL_PATH = os.path.join(MODEL_DIR, f"nifty_direction_model_5m{VER}.pkl")
METADATA_PATH = os.path.join(MODEL_DIR, f"model_metadata_5m{VER}.json")

def load_1m_bars(instrument_id: int, start_dt: int = 0, end_dt: int = 99999999999999):
    """Load 1m OHLC bars from DB candles view. Prices ÷100, dedup on dt."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    query = """
        SELECT dt, open_i, high_i, low_i, close_i, volume
        FROM candles WHERE instrument_id=? AND timeframe_id=1
        AND dt>=? AND dt<=? ORDER BY dt
    """
    df = pd.read_sql_query(query, conn, params=(instrument_id, start_dt, end_dt))
    conn.close()
    df = df.drop_duplicates(subset=["dt"], keep="last").reset_index(drop=True)
    for col in ["open_i","high_i","low_i","close_i"]:
        df[col] = df[col].astype(float) / 100.0
    df["volume"] = df["volume"].astype(float)
    df = df.rename(columns={"open_i":"Open","high_i":"High","low_i":"Low",
                             "close_i":"Close","volume":"Volume"})
    df["time_part"] = df["dt"].astype(str).str[8:12].astype(int)
    df = df[(df["time_part"]>=915)&(df["time_part"]<=1529)].copy()
    df["datetime"] = pd.to_datetime(df["dt"].astype(str), format="%Y%m%d%H%M%S")
    return df.set_index("datetime")


def load_vix_1m(start_dt=0, end_dt=99999999999999):
    """Load INDIA VIX 1m closes from DB."""
    df = load_1m_bars(instrument_id=6, start_dt=start_dt, end_dt=end_dt)
    return df["Close"]

def build_rolling_bar(bars):
    """Crush up to 5 1m candles into a rolling 5m structure. Port of sidecar.py:494."""
    if len(bars) < 1:
        return None
    recent = np.array(bars[-5:])
    return [recent[-1,0], np.max(recent[:,1]), np.min(recent[:,2]),
            recent[0,3], np.sum(recent[:,4])]


def _extract_features(bars, feature_cols, bar_dt, vix_closes=None):
    """Faithful port of sidecar.py:_extract_features (lines 511-667).
    bars: list of [Close,High,Low,Open,Volume] at 1m cadence.
    bar_dt: datetime of current bar for temporal features.
    vix_closes: parallel list of VIX closes.
    """
    # Build rolling 5m bars
    rolling_history = []
    for i in range(len(bars)):
        r = build_rolling_bar(bars[max(0,i-4):i+1])
        if r:
            rolling_history.append(r)

    df = pd.DataFrame(rolling_history, columns=["Close","High","Low","Open","Volume"])
    if len(df) < 2:
        return None, df

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
        vw = (c*v).rolling(20).sum()/v.rolling(20).sum()
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

    feat["feat_hour"] = bar_dt.hour
    feat["feat_minutes_since_open"] = (bar_dt.hour-9)*60+bar_dt.minute-15
    feat["feat_day_of_week"] = bar_dt.weekday()

    try:
        a20v = AverageTrueRange(h,l,c,20).average_true_range().iloc[-1]
        feat["feat_volatility"] = float(a20v/c.iloc[-1]*100)
    except: feat["feat_volatility"] = 0.5
    feat["feat_trend_strength"] = feat.get("feat_adx",20)

    try:
        e50 = c.ewm(span=50).mean().iloc[-1]
        feat["feat_futures_premium_proxy"] = float((c.iloc[-1]-e50)/c.iloc[-1]*100)
        e50_6 = c.ewm(span=50).mean().iloc[-7] if len(c)>=7 else e50
        pp = float((c.iloc[-7]-e50_6)/c.iloc[-7]*100) if len(c)>=7 else 0
        feat["feat_premium_change_rate"] = feat["feat_futures_premium_proxy"]-pp
    except: feat["feat_futures_premium_proxy"]=feat["feat_premium_change_rate"]=0

    if vix_closes and len(vix_closes)>=2:
        vix_s = pd.Series(vix_closes)
        vix_now = float(vix_s.iloc[-1])
        feat["feat_vix_level"] = vix_now
        feat["feat_vix_change"] = float(vix_s.pct_change().iloc[-1]*100) if len(vix_s)>1 else 0.0
        avg20 = float(vix_s.rolling(20).mean().iloc[-1]) if len(vix_s)>=20 else float(vix_s.mean())
        feat["feat_vix_vs_avg"] = ((vix_now-avg20)/avg20*100) if avg20>0 else 0.0
        feat["feat_vix_regime"] = 0.0 if vix_now<13 else (1.0 if vix_now<20 else (2.0 if vix_now<30 else 3.0))
    else:
        feat["feat_vix_level"]=16.0; feat["feat_vix_change"]=0.0
        feat["feat_vix_vs_avg"]=0.0; feat["feat_vix_regime"]=1.0

    try:
        ret = c.pct_change()
        ret_pos = (ret>0).astype(int)
        consec_up = ret_pos.groupby((ret_pos!=ret_pos.shift()).cumsum()).cumsum()*ret_pos
        feat["feat_consec_up"] = float(consec_up.iloc[-1])
        ret_neg = (ret<0).astype(int)
        consec_dn = ret_neg.groupby((ret_neg!=ret_neg.shift()).cumsum()).cumsum()*ret_neg
        feat["feat_consec_down"] = float(consec_dn.iloc[-1])
    except: feat["feat_consec_up"]=feat["feat_consec_down"]=0

    try:
        now_h = feat["feat_hour"]
        now_m = feat["feat_minutes_since_open"]+9*60+15
        feat["feat_session_position"] = max(0.0,min(1.0,(now_h*60+(now_m%60)-9*60-15)/375))
    except: feat["feat_session_position"] = 0.5

    try:
        ema9_s = EMAIndicator(c,9).ema_indicator()
        ema9_dir = ema9_s.diff().map(lambda x: 1 if x>0 else (-1 if x<0 else 0))
        rsi_s = RSIIndicator(c,14).rsi()
        rsi_dir = rsi_s.diff().map(lambda x: 1 if x>0 else (-1 if x<0 else 0))
        feat["feat_momentum_divergence"] = float(ema9_dir.iloc[-1]!=rsi_dir.iloc[-1])
    except: feat["feat_momentum_divergence"] = 0

    X = np.array([[feat.get(k,0) for k in feature_cols]])
    X = np.nan_to_num(X)
    return X, df

def replay_signals(nifty_df, vix_series, rolling_model, direction_model,
                   feature_cols, conf_threshold=35.0):
    """Replay the live signal pipeline minute-by-minute.
    Returns DataFrame with preds, probs, signals per minute."""
    bars_buffer = []
    vix_buffer = []
    results = []
    n_total = len(nifty_df)
    t0 = time_mod.time()
    current_date = None

    for i, (ts, row) in enumerate(nifty_df.iterrows()):
        # Reset buffers at each new trading day (mirrors sidecar's range=1d)
        if current_date is None or ts.date() != current_date:
            bars_buffer.clear()
            vix_buffer.clear()
            current_date = ts.date()

        bars_buffer.append([row["Close"], row["High"], row["Low"],
                           row["Open"], row["Volume"]])
        if ts in vix_series.index and pd.notna(vix_series.loc[ts]):
            vix_buffer.append(vix_series.loc[ts])
        elif len(vix_buffer) > 0:
            vix_buffer.append(vix_buffer[-1])
        else:
            vix_buffer.append(16.0)

        X, _ = _extract_features(bars_buffer, feature_cols, ts, vix_closes=list(vix_buffer))
        if X is None:
            continue

        rolling_pred = int(rolling_model.predict(X)[0])
        rolling_probs = rolling_model.predict_proba(X)[0].tolist()

        try:
            direction_pred = int(direction_model.predict(X)[0])
            direction_probs = direction_model.predict_proba(X)[0].tolist()
        except Exception:
            direction_pred = rolling_pred
            direction_probs = rolling_probs

        # Ensemble: average predict_proba per sidecar.py:746-748
        probs = [(r+d)/2 for r,d in zip(rolling_probs, direction_probs)]
        pred = int(np.argmax(probs))
        conf = probs[pred]*100

        signal = "NO TRADE"
        if conf > conf_threshold:
            if pred == 2: signal = "BUY CE"
            elif pred == 0: signal = "BUY PE"

        results.append({
            "dt": ts, "nifty_close": row["Close"], "vix_close": vix_buffer[-1],
            "pred": pred,
            "prob_down": round(probs[0]*100, 1),
            "prob_side": round(probs[1]*100, 1),
            "prob_up": round(probs[2]*100, 1),
            "conf": round(conf, 1),
            "signal": signal,
            "rolling_pred": rolling_pred,
            "rolling_down": round(rolling_probs[0]*100, 1),
            "rolling_side": round(rolling_probs[1]*100, 1),
            "rolling_up": round(rolling_probs[2]*100, 1),
            "direction_pred": direction_pred,
            "direction_down": round(direction_probs[0]*100, 1),
            "direction_side": round(direction_probs[1]*100, 1),
            "direction_up": round(direction_probs[2]*100, 1),
        })

        if (i+1)%5000 == 0:
            elapsed = time_mod.time()-t0
            rate = (i+1)/elapsed
            eta = (n_total-i-1)/rate if rate>0 else 0
            print(f"  [{i+1}/{n_total}] {rate:.0f} bars/sec, ETA {eta:.0f}s")

    return pd.DataFrame(results).set_index("dt")

def validate_against_csv(replay_df, csv_path):
    """Join replay signals against system_signals-18July.csv on (date, minute).
    Report agreement metrics."""
    csv = pd.read_csv(csv_path)
    csv["datetime"] = pd.to_datetime(csv["Date"]+" "+csv["Time"].str[:5],
                                      format="%Y-%m-%d %H:%M")
    csv = csv.set_index("datetime").sort_index()

    merged = replay_df.join(csv, how="inner", rsuffix="_live")
    if len(merged) == 0:
        print("ERROR: No overlapping timestamps!")
        return None

    print(f"\n{'='*60}")
    print(f"VALIDATION SUMMARY")
    print(f"{'='*60}")
    print(f"Replay signals:       {len(replay_df):,} minutes")
    print(f"CSV signals:          {len(csv):,} minutes")
    print(f"Matched (inner join): {len(merged):,} minutes")
    print(f"Date range:           {merged.index.min().date()} -> {merged.index.max().date()}")

    # Probability agreement
    prob_map = {"prob_down":"Prob_Down","prob_side":"Prob_Side","prob_up":"Prob_Up"}
    for rcol, lcol in prob_map.items():
        delta = (merged[rcol]-merged[lcol]).abs()
        print(f"\n  |\u0394 {rcol}|: mean={delta.mean():.2f}, median={delta.median():.2f}, "
              f"max={delta.max():.2f}, >5pct={((delta>5).sum()/len(merged)*100):.1f}%")

    # Prediction agreement
    csv_map = {"BUY CE":2, "BUY PE":0, "NO TRADE":1}
    merged["live_pred"] = merged["Signal"].map(csv_map)
    agree = (merged["live_pred"]==merged["pred"]).sum()
    total = len(merged)
    print(f"\n  Overall pred agreement: {agree}/{total} = {agree/total*100:.1f}%")
    for label, cid in [("DOWN(PE)",0),("SIDEWAYS",1),("UP(CE)",2)]:
        mask = merged["live_pred"]==cid
        if mask.sum()>0:
            a = (mask & (merged["pred"]==cid)).sum()
            print(f"    {label}: {a}/{mask.sum()} = {a/mask.sum()*100:.1f}%")

    # Trade/no-trade agreement
    merged["live_trade"] = merged["Signal"].isin(["BUY CE","BUY PE"])
    merged["replay_trade"] = merged["signal"].isin(["BUY CE","BUY PE"])
    ta = (merged["live_trade"]==merged["replay_trade"]).sum()
    print(f"\n  Trade/no-trade agreement: {ta}/{total} = {ta/total*100:.1f}%")

    # By hour
    print(f"\n  Disagreement by hour:")
    merged["disagree"] = merged["live_pred"]!=merged["pred"]
    for h in sorted(merged.index.hour.unique()):
        s = merged[merged.index.hour==h]
        if len(s)>0:
            print(f"    {h:02d}:00 - {len(s):,} bars, {s['disagree'].mean()*100:.1f}% disagree")

    # By date (top 10)
    print(f"\n  Disagreement by date (top 10):")
    merged["date"] = merged.index.date
    daily = merged.groupby("date")["disagree"].agg(["count","mean"])
    for dt, row in daily.sort_values("mean",ascending=False).head(10).iterrows():
        print(f"    {dt}: {row['count']:,} bars, {row['mean']*100:.1f}% disagree")

    # Confidence delta
    conf_delta = (merged["conf"]-merged["Confidence"]).abs()
    print(f"\n  |\u0394 confidence|: mean={conf_delta.mean():.2f}, median={conf_delta.median():.2f}")

    return merged

def main():
    parser = argparse.ArgumentParser(description="Step 1: Offline replay harness")
    parser.add_argument("--skip-cache", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--date-start", type=str, default="20260428")
    parser.add_argument("--date-end", type=str, default="20260629")
    args = parser.parse_args()

    start_dt = int(args.date_start+"000000")
    end_dt = int(args.date_end+"235959")
    cache_path = os.path.join(DATA_DIR, f"replay_signals_{args.date_start}_{args.date_end}.csv")

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    print("Loading models...")
    if not os.path.exists(ROLLING_MODEL_PATH):
        print(f"ERROR: Rolling model not found at {ROLLING_MODEL_PATH}")
        sys.exit(1)
    rolling_model = joblib.load(ROLLING_MODEL_PATH)
    print(f"  Rolling:  {os.path.basename(ROLLING_MODEL_PATH)}")

    direction_model = None
    if os.path.exists(DIRECTION_MODEL_PATH):
        direction_model = joblib.load(DIRECTION_MODEL_PATH)
        print(f"  Direction: {os.path.basename(DIRECTION_MODEL_PATH)}")
    else:
        print(f"  Direction: NOT FOUND (will fallback to rolling-only)")

    with open(METADATA_PATH) as f:
        metadata = json.load(f)
    feature_cols = metadata["feature_columns"]
    print(f"  Metadata:  {os.path.basename(METADATA_PATH)} ({len(feature_cols)} features)")

    if args.validate_only:
        if not os.path.exists(cache_path):
            print(f"ERROR: No cache at {cache_path}")
            sys.exit(1)
        print(f"\nLoading cached signals from {cache_path}")
        replay_df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
    elif not args.skip_cache and os.path.exists(cache_path):
        print(f"\nLoading cached signals from {cache_path}")
        replay_df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
    else:
        print(f"\nLoading Nifty 50 1m bars ({args.date_start} -> {args.date_end})...")
        nifty_df = load_1m_bars(instrument_id=9, start_dt=start_dt, end_dt=end_dt)
        print(f"  {len(nifty_df):,} Nifty 1m bars")

        print("Loading INDIA VIX 1m bars...")
        vix_series = load_vix_1m(start_dt=start_dt, end_dt=end_dt)
        print(f"  {len(vix_series):,} VIX 1m bars")

        if direction_model is None:
            direction_model = rolling_model

        # Process day-by-day to keep per-call memory bounded (~375 bars/day)
        dates = sorted(set(nifty_df.index.date))
        print(f"\nReplaying signals ({len(dates)} days, {len(nifty_df):,} minutes)...")
        daily_dfs = []
        for d, day_date in enumerate(dates):
            try:
                day_mask = nifty_df.index.date == day_date
                day_nifty = nifty_df[day_mask]
                day_vix = vix_series[vix_series.index.date == day_date]
                day_replay = replay_signals(day_nifty, day_vix, rolling_model,
                                            direction_model, feature_cols)
                if len(day_replay) > 0:
                    daily_dfs.append(day_replay)
                print(f"  [{d+1}/{len(dates)}] {day_date}: {len(day_replay)} signals")
            except Exception as e:
                print(f"  [{d+1}/{len(dates)}] {day_date}: ERROR - {e}")
            gc.collect()

        replay_df = pd.concat(daily_dfs).sort_index()
        print(f"  {len(replay_df):,} total signal rows generated")
        replay_df.to_csv(cache_path, index=True)
        print(f"  Cached -> {cache_path}")

    # ── Validation ──
    print(f"\nValidating against {SIGNALS_CSV}...")
    if not os.path.exists(SIGNALS_CSV):
        print(f"WARNING: CSV not found, skipping validation.")
        return

    merged = validate_against_csv(replay_df, SIGNALS_CSV)

    report_path = os.path.join(REPORT_DIR, "step1_replay_validation.md")
    print(f"\n{'='*60}")
    print(f"Step 1 complete. Report -> {report_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
