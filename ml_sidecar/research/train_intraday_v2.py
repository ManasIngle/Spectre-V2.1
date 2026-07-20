#!/usr/bin/env python3
"""
Step 3 — Retrain Rolling + Direction (walk-forward, calibrated).
"""
import os, sys, json, sqlite3, time as time_mod, gc, warnings
import numpy as np
import pandas as pd
import joblib
from datetime import datetime, timedelta, date
import zoneinfo
warnings.filterwarnings("ignore")

from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import f1_score, brier_score_loss
import xgboost as xgb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = "/Users/manasingle/Edge/June/Miequity/archive_2020_smart.db"
ARTIFACT_DIR = os.path.join(ROOT, "artifacts")
DATA_DIR = os.path.join(ROOT, "data")
REPORT_DIR = os.path.join(ROOT, "reports")
IST = zoneinfo.ZoneInfo("Asia/Kolkata")
RANDOM_SEED = 42
FORWARD_BARS = 30
THRESHOLD_PCT = 0.08
PURGE_BARS = 30
EMBARGO_DAYS = 1

XGB_PARAMS = {"n_estimators":300,"max_depth":6,"learning_rate":0.05,
              "subsample":0.8,"colsample_bytree":0.8,"min_child_weight":5,
              "objective":"multi:softprob","eval_metric":"mlogloss",
              "random_state":RANDOM_SEED,"n_jobs":-1,"verbosity":0}

os.makedirs(ARTIFACT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def load_1m_bars(instrument_id, start_dt=0, end_dt=99999999999999):
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    df = pd.read_sql_query("""
        SELECT dt, open_i, high_i, low_i, close_i, volume
        FROM candles WHERE instrument_id=? AND timeframe_id=1
        AND dt>=? AND dt<=? ORDER BY dt
    """, conn, params=(instrument_id, start_dt, end_dt))
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
    df["datetime"] = df["datetime"].dt.tz_localize(IST)
    return df.set_index("datetime")

def extract_v2_features_day(nifty_day, vix_day):
    """Extract v2 features for one trading day. Returns DataFrame of features."""
    from ta.trend import ADXIndicator, MACD, EMAIndicator
    from ta.momentum import RSIIndicator
    from ta.volatility import BollingerBands, AverageTrueRange
    
    all_bars = []
    vix_closes = []
    results = []
    for ts, row in nifty_day.iterrows():
        all_bars.append([row["Close"],row["High"],row["Low"],row["Open"],row["Volume"]])
        if ts in vix_day.index and pd.notna(vix_day.loc[ts]):
            vix_closes.append(float(vix_day.loc[ts]))
        elif vix_closes:
            vix_closes.append(vix_closes[-1])
        else:
            vix_closes.append(16.0)
        
        # Build rolling 5m bars
        bars_5m = []
        for i in range(len(all_bars)):
            recent = np.array(all_bars[max(0,i-4):i+1])
            bars_5m.append([recent[-1,0], np.max(recent[:,1]), np.min(recent[:,2]),
                           recent[0,3], np.sum(recent[:,4])])
        
        df5 = pd.DataFrame(bars_5m, columns=["Close","High","Low","Open","Volume"])
        if len(df5) < 2:
            continue
        
        c, h, l = df5.Close, df5.High, df5.Low
        f = {}
        try: f["feat_rsi"] = float(RSIIndicator(c,14).rsi().iloc[-1])
        except: f["feat_rsi"] = 50
        try:
            adx = ADXIndicator(h,l,c,14)
            f["feat_adx"] = float(adx.adx().iloc[-1])
            f["feat_di_plus"] = float(adx.adx_pos().iloc[-1])
            f["feat_di_minus"] = float(adx.adx_neg().iloc[-1])
            f["feat_di_diff"] = f["feat_di_plus"] - f["feat_di_minus"]
        except: f.update({"feat_adx":20,"feat_di_plus":20,"feat_di_minus":20,"feat_di_diff":0})
        try: f["feat_macd_hist"] = float(MACD(c).macd_diff().iloc[-1])
        except: f["feat_macd_hist"] = 0
        try:
            e9=EMAIndicator(c,9).ema_indicator().iloc[-1]; e21=EMAIndicator(c,21).ema_indicator().iloc[-1]
            f["feat_ema_spread"] = float((e9-e21)/c.iloc[-1]*100)
        except: f["feat_ema_spread"] = 0
        # VWAP replacement: close vs 20-bar MA
        try:
            ma20 = c.rolling(20).mean().iloc[-1]
            f["feat_close_ma_dev"] = float((c.iloc[-1]-ma20)/c.iloc[-1]*100) if pd.notna(ma20) else 0
        except: f["feat_close_ma_dev"] = 0
        try:
            at=AverageTrueRange(h,l,c,10).average_true_range()
            hl2=(h+l)/2; upper=hl2+2*at; lower=hl2-2*at
            f["feat_st_direction"] = 1 if c.iloc[-1]>upper.iloc[-2] else (-1 if c.iloc[-1]<lower.iloc[-2] else 0)
        except: f["feat_st_direction"] = 0
        for n,k in [(6,"feat_roc_6"),(12,"feat_roc_12")]:
            try: f[k]=float(c.pct_change(n).iloc[-1]*100)
            except: f[k]=0
        try:
            bb=BollingerBands(c,20,2); rng=bb.bollinger_hband().iloc[-1]-bb.bollinger_lband().iloc[-1]
            f["feat_bb_pos"]=float((c.iloc[-1]-bb.bollinger_lband().iloc[-1])/rng) if rng>0 else 0.5
        except: f["feat_bb_pos"]=0.5
        try:
            at14=AverageTrueRange(h,l,c,14).average_true_range().iloc[-1]
            f["feat_atr_move"]=float((c.iloc[-1]-c.iloc[-2])/at14) if at14>0 else 0
        except: f["feat_atr_move"]=0
        for lag,k in [(1,"feat_ret_1"),(2,"feat_ret_2"),(3,"feat_ret_3")]:
            try: f[k]=float(c.pct_change(lag).iloc[-1]*100)
            except: f[k]=0
        try: f["feat_slow_rsi"]=float(RSIIndicator(c,42).rsi().iloc[-1])
        except: f["feat_slow_rsi"]=50
        try:
            ms=MACD(c,52,24,18); f["feat_slow_macd_hist"]=float(ms.macd_diff().iloc[-1])
        except: f["feat_slow_macd_hist"]=0
        try:
            a30=AverageTrueRange(h,l,c,30).average_true_range(); h2=(h+l)/2
            u2=h2+2*a30; l2=h2-2*a30
            f["feat_slow_st_dir"]=1 if c.iloc[-1]>u2.iloc[-2] else (-1 if c.iloc[-1]<l2.iloc[-2] else 0)
        except: f["feat_slow_st_dir"]=0
        
        f["feat_equity_weighted_ret"] = 0.0
        f["feat_equity_advance_pct"] = 0.0
        f["feat_equity_momentum"] = 0.0
        f["feat_hour"] = ts.hour
        f["feat_minutes_since_open"] = (ts.hour-9)*60+ts.minute-15
        f["feat_day_of_week"] = ts.weekday()
        try:
            a20v=AverageTrueRange(h,l,c,20).average_true_range().iloc[-1]
            f["feat_volatility"]=float(a20v/c.iloc[-1]*100)
        except: f["feat_volatility"]=0.5
        f["feat_trend_strength"]=f.get("feat_adx",20)
        try:
            e50=c.ewm(span=50).mean().iloc[-1]
            f["feat_futures_premium_proxy"]=float((c.iloc[-1]-e50)/c.iloc[-1]*100)
            e50_6=c.ewm(span=50).mean().iloc[-7] if len(c)>=7 else e50
            pp=float((c.iloc[-7]-e50_6)/c.iloc[-7]*100) if len(c)>=7 else 0
            f["feat_premium_change_rate"]=f["feat_futures_premium_proxy"]-pp
        except: f["feat_futures_premium_proxy"]=f["feat_premium_change_rate"]=0
        try:
            ret=c.pct_change(); rp=(ret>0).astype(int)
            cu=rp.groupby((rp!=rp.shift()).cumsum()).cumsum()*rp; f["feat_consec_up"]=float(cu.iloc[-1])
            rn=(ret<0).astype(int); cd=rn.groupby((rn!=rn.shift()).cumsum()).cumsum()*rn
            f["feat_consec_down"]=float(cd.iloc[-1])
        except: f["feat_consec_up"]=f["feat_consec_down"]=0
        f["feat_session_position"]=max(0.0,min(1.0,(ts.hour*60+ts.minute-9*60-15)/375))
        try:
            e9d=EMAIndicator(c,9).ema_indicator().diff().map(lambda x:1 if x>0 else (-1 if x<0 else 0))
            rd=RSIIndicator(c,14).rsi().diff().map(lambda x:1 if x>0 else (-1 if x<0 else 0))
            f["feat_momentum_divergence"]=float(e9d.iloc[-1]!=rd.iloc[-1])
        except: f["feat_momentum_divergence"]=0
        
        if vix_closes and len(vix_closes)>=2:
            vs=pd.Series(vix_closes); vn=float(vs.iloc[-1])
            f["feat_vix_level"]=vn
            f["feat_vix_change"]=float(vs.pct_change().iloc[-1]*100) if len(vs)>1 else 0
            avg20=float(vs.rolling(20).mean().iloc[-1]) if len(vs)>=20 else float(vs.mean())
            f["feat_vix_vs_avg"]=((vn-avg20)/avg20*100) if avg20>0 else 0
            f["feat_vix_regime"]=0.0 if vn<13 else (1.0 if vn<20 else (2.0 if vn<30 else 3.0))
        else:
            for k in ["feat_vix_level","feat_vix_change","feat_vix_vs_avg","feat_vix_regime"]: f[k]=0.0
        
        results.append({"dt":ts, **f})
    return pd.DataFrame(results).set_index("dt") if results else pd.DataFrame()

V2_FEATS = [
    "feat_rsi","feat_adx","feat_di_plus","feat_di_minus","feat_di_diff",
    "feat_macd_hist","feat_ema_spread","feat_close_ma_dev","feat_st_direction",
    "feat_roc_6","feat_roc_12","feat_bb_pos","feat_atr_move",
    "feat_ret_1","feat_ret_2","feat_ret_3",
    "feat_slow_rsi","feat_slow_macd_hist","feat_slow_st_dir",
    "feat_equity_weighted_ret","feat_equity_advance_pct","feat_equity_momentum",
    "feat_hour","feat_minutes_since_open","feat_day_of_week",
    "feat_volatility","feat_trend_strength",
    "feat_futures_premium_proxy","feat_premium_change_rate",
    "feat_consec_up","feat_consec_down","feat_session_position",
    "feat_momentum_divergence",
    "feat_vix_level","feat_vix_change","feat_vix_vs_avg","feat_vix_regime",
]

def make_labels(prices, forward_bars=FORWARD_BARS, threshold=THRESHOLD_PCT/100):
    """Create symmetric DOWN/SIDE/UP labels. Returns pd.Series aligned with prices."""
    p = np.array(prices)
    n = len(p)
    labels = np.full(n, 1, dtype=int)  # default SIDE
    for i in range(n - forward_bars):
        fwd_ret = (p[i+forward_bars] - p[i]) / p[i]
        if fwd_ret > threshold:
            labels[i] = 2  # UP
        elif fwd_ret < -threshold:
            labels[i] = 0  # DOWN
    return pd.Series(labels, index=prices.index)

def compute_brier(y_true, y_proba, n_classes=3):
    """Multi-class Brier score (mean over classes)."""
    y_onehot = np.eye(n_classes)[y_true.astype(int)]
    return np.mean((y_proba - y_onehot)**2)

def build_training_data(start_yr, end_yr, cache_path=None):
    """Generate features+labels for a year range. Caches to parquet."""
    if cache_path and os.path.exists(cache_path):
        print(f"  Loading cached: {cache_path}")
        df = pd.read_parquet(cache_path)
        return df[V2_FEATS].values, df["label"].values, df["close"].values, df
    
    print(f"  Building training data {start_yr}-{end_yr}...")
    # Process year by year, day by day
    all_dfs = []
    for yr in range(start_yr, end_yr+1):
        yr_start = int(f"{yr}0101000000")
        yr_end = int(f"{yr}1231235959")
        nifty = load_1m_bars(9, yr_start, yr_end)
        vix = load_1m_bars(6, yr_start, yr_end)
        vix_c = vix["Close"] if len(vix)>0 else pd.Series(dtype=float)
        dates = sorted(set(nifty.index.date))
        for d in dates:
            dm = nifty.index.date == d
            dn = nifty[dm]; dv = vix_c[vix_c.index.date == d] if len(vix_c)>0 else pd.Series(dtype=float)
            if len(dn) < 5: continue
            feats = extract_v2_features_day(dn, dv)
            if len(feats) < 5: continue
            feats["label"] = make_labels(dn["Close"].loc[feats.index])
            feats["close"] = dn["Close"].loc[feats.index]
            feats = feats.dropna(subset=V2_FEATS + ["label"])
            if len(feats) > 0:
                all_dfs.append(feats)
        gc.collect()
    
    df = pd.concat(all_dfs).sort_index()
    if cache_path:
        df.to_parquet(cache_path)
        print(f"  Cached {len(df):,} rows -> {cache_path}")
    return df[V2_FEATS].values, df["label"].values, df["close"].values, df

def get_fold_boundaries(dates_series, test_months=6):
    """Return list of (train_end_date, test_start_date, test_end_date) tuples
    for expanding-window walk-forward with 6-month test folds."""
    dates = sorted(set(dates_series))
    min_date, max_date = min(dates), max(dates)
    boundaries = []
    # First train window: at least 2 years
    train_end = date(min_date.year + 2, min_date.month, min_date.day)
    while True:
        test_start = train_end + timedelta(days=EMBARGO_DAYS)
        test_end_month = test_start.month + test_months
        test_end_year = test_start.year + (test_end_month - 1) // 12
        test_end_month = ((test_end_month - 1) % 12) + 1
        test_end = date(test_end_year, test_end_month, 1) - timedelta(days=1)
        if test_end > max_date:
            test_end = max_date
        if test_start >= max_date:
            break
        boundaries.append((train_end, test_start, test_end))
        train_end = test_end
        if test_end >= max_date:
            break
    return boundaries

def train_walkforward(X, y, dates, close_prices, model_name="model"):
    """Walk-forward training with purge+embargo. Returns OOF predictions, model, calibrators."""
    boundaries = get_fold_boundaries(dates)
    print(f"  {model_name}: {len(boundaries)} folds")
    
    oof_probs = np.zeros((len(y), 3))
    oof_preds = np.zeros(len(y))
    fold_metrics = []
    models = []
    
    le = LabelEncoder()
    y_enc = le.fit_transform(y.astype(int))
    
    for fi, (train_end_d, test_start_d, test_end_d) in enumerate(boundaries):
        # Masks with purge: train ends at train_end, test starts after embargo
        train_mask = dates <= pd.Timestamp(train_end_d)
        # Purge: remove last PURGE_BARS from train
        train_idx = np.where(train_mask)[0]
        if len(train_idx) > PURGE_BARS:
            train_idx = train_idx[:-PURGE_BARS]
        
        test_mask = (dates >= pd.Timestamp(test_start_d)) & (dates <= pd.Timestamp(test_end_d))
        test_idx = np.where(test_mask)[0]
        
        if len(test_idx) < 100:
            print(f"    Fold {fi+1}: test too small ({len(test_idx)}), skipping")
            continue
        
        X_train, y_train = X[train_idx], y_enc[train_idx]
        X_test, y_test = X[test_idx], y_enc[test_idx]
        
        model = xgb.XGBClassifier(**XGB_PARAMS)
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
        
        test_probs = model.predict_proba(X_test)
        test_preds = model.predict(X_test)
        
        oof_probs[test_idx] = test_probs
        oof_preds[test_idx] = test_preds
        models.append(model)
        
        f1 = f1_score(y_test, test_preds, average="macro")
        p, r, f, _ = precision_recall_fscore_support(y_test, test_preds, labels=[0,1,2])
        brier = compute_brier(y_test, test_probs)
        
        fold_metrics.append({
            "fold": fi+1, "train_end": train_end_d, "test_start": test_start_d,
            "test_end": test_end_d, "n_train": len(X_train), "n_test": len(X_test),
            "f1_macro": round(f1,4),
            "prec_down": round(p[0],3), "prec_side": round(p[1],3), "prec_up": round(p[2],3),
            "rec_down": round(r[0],3), "rec_side": round(r[1],3), "rec_up": round(r[2],3),
            "brier": round(brier,4),
        })
        print(f"    Fold {fi+1}: {test_start_d}->{test_end_d}, n={len(X_test)}, f1={f1:.3f}, brier={brier:.3f}")
    
    # Best model = last fold (most recent)
    final_model = models[-1] if models else None
    
    # Isotonic calibration per class
    calibrators = []
    cal_probs = np.zeros_like(oof_probs)
    for c in range(3):
        mask = oof_preds >= 0  # all samples where we have predictions
        if oof_probs[mask, c].sum() > 0:
            iso = IsotonicRegression(out_of_bounds="clip")
            iso.fit(oof_probs[mask, c], (y_enc[mask]==c).astype(float))
            cal_probs[mask, c] = iso.transform(oof_probs[mask, c])
            calibrators.append(iso)
        else:
            calibrators.append(None)
    
    # Normalize calibrated probs to sum to 1
    cal_probs = cal_probs / cal_probs.sum(axis=1, keepdims=True)
    cal_preds = np.argmax(cal_probs, axis=1)
    
    return {
        "model": final_model,
        "calibrators": calibrators,
        "oof_probs": oof_probs,
        "oof_preds": oof_preds,
        "cal_probs": cal_probs,
        "cal_preds": cal_preds,
        "y_true": y_enc,
        "fold_metrics": fold_metrics,
        "models": models,
    }

def main():
    print("="*60)
    print("Step 3 — Retrain Rolling + Direction (v2)")
    print("="*60)
    
    # Build training data for full period (2020-2026)
    cache = os.path.join(DATA_DIR, "training_v2.parquet")
    X, y, closes, df = build_training_data(2020, 2026, cache)
    dates = pd.Series(df.index.date)
    print(f"\nTraining data: {len(X):,} rows, {len(V2_FEATS)} features")
    print(f"Label dist: DOWN={(y==0).sum()}, SIDE={(y==1).sum()}, UP={(y==2).sum()}")
    
    # Train Rolling model (full feature set, all data)
    print("\n--- Rolling Model ---")
    rolling_result = train_walkforward(X, y, df.index.to_series(), closes, "Rolling")
    
    # Train Direction model (same features, same representation)
    print("\n--- Direction Model ---")
    direction_result = train_walkforward(X, y, df.index.to_series(), closes, "Direction")
    
    if rolling_result["model"] is None or direction_result["model"] is None:
        print("ERROR: Training failed — no folds produced models")
        return
    
    # ── Save artifacts ──
    rolling_path = os.path.join(ARTIFACT_DIR, "nifty_rolling_v2.pkl")
    direction_path = os.path.join(ARTIFACT_DIR, "nifty_direction_v2.pkl")
    cal_path = os.path.join(ARTIFACT_DIR, "intraday_v2_calibrators.pkl")
    meta_path = os.path.join(ARTIFACT_DIR, "intraday_v2_metadata.json")
    
    joblib.dump(rolling_result["model"], rolling_path)
    joblib.dump(direction_result["model"], direction_path)
    joblib.dump({"rolling": rolling_result["calibrators"], "direction": direction_result["calibrators"]}, cal_path)
    
    metadata = {
        "feature_columns": V2_FEATS,
        "horizon_bars": FORWARD_BARS,
        "threshold_pct": THRESHOLD_PCT,
        "asymmetric": False,
        "calibration": "isotonic_per_class",
        "train_period": "2020-2026",
        "walk_forward_folds": len(rolling_result["fold_metrics"]),
        "v1_features_dropped": ["feat_rel_vol", "feat_vol_trend", "feat_vwap_dev"],
        "v2_features_added": ["feat_close_ma_dev"],
        "seed": RANDOM_SEED,
    }
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    
    print(f"\nArtifacts saved:")
    print(f"  {rolling_path}")
    print(f"  {direction_path}")
    print(f"  {cal_path}")
    print(f"  {meta_path}")
    
    # ── Generate report ──
    report = [
        "# Step 3 — V2 Retraining Report",
        f"**Date:** {datetime.now(IST).strftime('%Y-%m-%d')}",
        "",
        f"## Configuration",
        f"- Features: {len(V2_FEATS)} (dropped feat_rel_vol, feat_vol_trend, feat_vwap_dev; added feat_close_ma_dev)",
        f"- Labels: {FORWARD_BARS}-bar forward, symmetric +/-{THRESHOLD_PCT}%",
        f"- Walk-forward: expanding window, {TEST_MONTHS}-month folds",
        f"- Purge: {PURGE_BARS} bars, Embargo: {EMBARGO_DAYS} day",
        f"- Calibration: isotonic per class on OOF",
        f"- Scoring: f1_macro",
        "",
        f"## Label Distribution",
        f"DOWN: {(y==0).sum():,} ({(y==0).sum()/len(y)*100:.1f}%)",
        f"SIDE: {(y==1).sum():,} ({(y==1).sum()/len(y)*100:.1f}%)",
        f"UP: {(y==2).sum():,} ({(y==2).sum()/len(y)*100:.1f}%)",
        "",
    ]
    
    for model_name, result in [("Rolling", rolling_result), ("Direction", direction_result)]:
        report.append(f"## {model_name} Model")
        report.append("")
        report.append("### Per-Fold Metrics")
        report.append("| Fold | Train End | Test Period | N | F1 | Brier | Prec D/S/U | Rec D/S/U |")
        report.append("|------|-----------|-------------|---|---|-------|-------------|------------|")
        for fm in result["fold_metrics"]:
            report.append(f"| {fm['fold']} | {fm['train_end']} | {fm['test_start']}->{fm['test_end']} | "
                         f"{fm['n_test']} | {fm['f1_macro']:.3f} | {fm['brier']:.3f} | "
                         f"{fm['prec_down']}/{fm['prec_side']}/{fm['prec_up']} | "
                         f"{fm['rec_down']}/{fm['rec_side']}/{fm['rec_up']} |")
        
        # Overall metrics
        mask = result["oof_preds"] >= 0
        yt = result["y_true"][mask]
        yp = result["oof_preds"][mask]
        probs = result["oof_probs"][mask]
        cal_probs = result["cal_probs"][mask]
        cal_preds = result["cal_preds"][mask]
        
        f1_raw = f1_score(yt, yp, average="macro")
        f1_cal = f1_score(yt, cal_preds, average="macro")
        brier_raw = compute_brier(yt, probs)
        brier_cal = compute_brier(yt, cal_probs)
        
        report.append("")
        report.append("### Overall OOF")
        report.append(f"| Metric | Before Cal | After Cal |")
        report.append(f"|---|---|---|")
        report.append(f"| F1 (macro) | {f1_raw:.4f} | {f1_cal:.4f} |")
        report.append(f"| Brier | {brier_raw:.4f} | {brier_cal:.4f} |")
        
        # Calibrated confidence buckets vs accuracy
        report.append("")
        report.append("### Calibrated Confidence Buckets vs Accuracy")
        report.append("| Conf Bucket | N | Accuracy |")
        report.append("|-------------|---|----------|")
        cal_conf = np.max(cal_probs, axis=1) * 100
        cal_acc = (cal_preds == yt).astype(float)
        for lo in range(30, 100, 5):
            mask_b = (cal_conf >= lo) & (cal_conf < lo+5)
            if mask_b.sum() > 0:
                report.append(f"| {lo}-{lo+5} | {mask_b.sum():,} | {cal_acc[mask_b].mean()*100:.1f}% |")
    
    rpath = os.path.join(REPORT_DIR, "step3_retrain_v2.md")
    with open(rpath, "w") as f:
        f.write("\n".join(report))
    print(f"\nReport -> {rpath}")

if __name__ == "__main__":
    from sklearn.preprocessing import LabelEncoder
    main()
