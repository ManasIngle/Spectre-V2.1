#!/usr/bin/env python3
"""
Step 4 — Meta-labeler: "should this trade be taken?"

Trains an XGBoost binary classifier on backtest trade outcomes
to filter signals. Uses v2 ensemble (from Step 3) to regenerate
trades, then trains a meta-model on trade-level features.
"""
import os, sys, json, gc, warnings
import numpy as np
import pandas as pd
import joblib
from datetime import datetime
import zoneinfo
warnings.filterwarnings("ignore")

from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import f1_score
import xgboost as xgb

ROOT = os.path.dirname(os.path.abspath(__file__))
ARTIFACT_DIR = os.path.join(ROOT, "artifacts")
REPORT_DIR = os.path.join(ROOT, "reports")
IST = zoneinfo.ZoneInfo("Asia/Kolkata")
RANDOM_SEED = 42

os.makedirs(ARTIFACT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

META_PARAMS = {"n_estimators":200,"max_depth":4,"learning_rate":0.03,
               "subsample":0.8,"colsample_bytree":0.7,"min_child_weight":10,
               "objective":"binary:logistic","eval_metric":"logloss",
               "random_state":RANDOM_SEED,"n_jobs":-1,"verbosity":0}

def build_metalabel_features(trades_df):
    """Build entry-time-only features from trade records (no lookahead)."""
    df = trades_df.copy()
    df["hour"] = df["entry_ts"].apply(lambda t: t.hour)
    df["mins_open"] = df["entry_ts"].apply(lambda t: (t.hour-9)*60+t.minute-15)
    df["dow"] = df["entry_ts"].apply(lambda t: t.weekday())
    df["entry_date"] = df["entry_ts"].apply(lambda t: t.date())
    
    # Signal side
    df["is_ce"] = (df["opt_type"]=="CE").astype(int)
    
    # Consecutive same-side signals (approximate: count within same day)
    df["consec"] = df.groupby(["entry_date","opt_type"]).cumcount()
    
    features = pd.DataFrame({
        "label": (df["net_pnl"] > 0).astype(int),
        "entry_conf": df["entry_conf"],
        "hour": df["hour"],
        "mins_since_open": df["mins_open"],
        "day_of_week": df["dow"],
        "is_ce": df["is_ce"],
        "consec_same_side": df["consec"].clip(0,10),
        "held_mins": df["held_mins"],
        "entry_spot": df["entry_spot"],
        "entry_premium": df["entry_premium"],
    }, index=df.index)
    return features.dropna()

def main():
    print("="*60)
    print("Step 4 — Meta-labeler")
    print("="*60)
    
    # Load trades from Step 2 full backtest (variant D)
    # Regenerate using backtest_geometry module
    sys.path.insert(0, ROOT)
    from backtest_geometry import (load_1m_bars, compute_atr, VARIANTS,
                                    run_backtest, run_all_variants,
                                    trade_strike, compute_premium, LOT_SIZE,
                                    BROKERAGE, SLIPPAGE_BPS, RISK_FREE_RATE)
    
    # Load signals
    sig_cache = os.path.join(ROOT, "data", "signals_20200101_20260629.csv")
    if not os.path.exists(sig_cache):
        print(f"ERROR: Signal cache not found: {sig_cache}")
        return
    
    print("Loading signals...")
    signals = pd.read_csv(sig_cache, index_col=0, parse_dates=True)
    
    # Load full data and run D variant
    print("Loading full-period data...")
    nifty = load_1m_bars(9, 20200101000000, 20260629235959)
    vix = load_1m_bars(6, 20200101000000, 20260629235959)
    vix_s = vix["Close"] if len(vix)>0 else pd.Series(dtype=float)
    atr = compute_atr(nifty)
    
    print("Running D variant backtest...")
    bt = run_backtest(nifty, vix_s, signals, atr,
                      timeout_min=30, target_atr=0.0, sl_atr=0.0, conf_threshold=35)
    
    if not bt.trades:
        print("ERROR: No trades generated")
        return
    
    trades_df = pd.DataFrame(bt.trades)
    print(f"Total trades: {len(trades_df)}")
    
    # Filter to 2023-2026 OOF period
    trades_df["entry_dt"] = pd.to_datetime(trades_df["entry_ts"])
    oof_mask = trades_df["entry_dt"] >= "2023-01-01"
    trades_oof = trades_df[oof_mask]
    print(f"OOF trades (2023+): {len(trades_oof)}")
    
    # Build features
    feats = build_metalabel_features(trades_oof)
    print(f"Label dist: win={(feats['label']==1).sum()}, loss={(feats['label']==0).sum()}")
    
    # Walk-forward by year
    feats["year"] = trades_oof["entry_dt"].dt.year
    years = sorted(feats["year"].unique())
    print(f"Years: {years}")
    
    oof_probs = np.zeros(len(feats))
    oof_preds = np.zeros(len(feats))
    
    feature_cols = [c for c in feats.columns if c not in ("label","year")]
    
    for yi, yr in enumerate(years):
        if yi == 0: continue  # Need at least 1 year of training
        train_mask = feats["year"] < yr
        test_mask = feats["year"] == yr
        X_tr, y_tr = feats.loc[train_mask, feature_cols].values, feats.loc[train_mask, "label"].values
        X_te, y_te = feats.loc[test_mask, feature_cols].values, feats.loc[test_mask, "label"].values
        
        if len(X_tr) < 100 or len(X_te) < 20:
            continue
        
        model = xgb.XGBClassifier(**META_PARAMS)
        model.fit(X_tr, y_tr, verbose=False)
        probs = model.predict_proba(X_te)[:,1]
        preds = model.predict(X_te)
        oof_probs[test_mask.values] = probs
        oof_preds[test_mask.values] = preds
        
        f1 = f1_score(y_te, preds)
        print(f"  {yr}: n_train={len(X_tr)}, n_test={len(X_te)}, f1={f1:.3f}")
    
    # Calibration
    mask = oof_probs > 0
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(oof_probs[mask], feats["label"].values[mask])
    cal_probs = iso.transform(oof_probs[mask])
    cal_probs_full = np.zeros_like(oof_probs)
    cal_probs_full[mask] = cal_probs
    
    # Evaluate at cutoffs
    print("\n--- Meta-labeler Cutoff Evaluation ---")
    print(f"{'Cutoff':<10} {'Trades':>8} {'Win%':>8} {'Net PnL':>12} {'PF':>6}")
    print("-"*50)
    
    base_net = trades_oof["net_pnl"].sum()
    base_n = len(trades_oof)
    
    df_eval = trades_oof.copy()
    df_eval["meta_score"] = cal_probs_full
    
    for cutoff in [0.0, 0.4, 0.5, 0.6]:
        if cutoff == 0.0:
            filtered = df_eval
        else:
            filtered = df_eval[df_eval["meta_score"] >= cutoff]
        
        n = len(filtered)
        if n == 0:
            print(f"{cutoff:<10} {0:>8} {'-':>8} {0:>12} {'-':>6}")
            continue
        net = filtered["net_pnl"].sum()
        wins = (filtered["net_pnl"] > 0).sum()
        wr = wins/n*100
        gross_p = filtered[filtered["net_pnl"]>0]["net_pnl"].sum()
        gross_l = abs(filtered[filtered["net_pnl"]<=0]["net_pnl"].sum())
        pf = gross_p/gross_l if gross_l > 0 else float('inf')
        
        print(f"{cutoff:<10} {n:>8} {wr:>7.1f}% {net:>11,.0f} {pf:>5.2f}")
    
    # Save model
    final_model = xgb.XGBClassifier(**META_PARAMS)
    final_model.fit(feats[feature_cols].values, feats["label"].values, verbose=False)
    
    model_path = os.path.join(ARTIFACT_DIR, "metalabel_v1.pkl")
    cal_path = os.path.join(ARTIFACT_DIR, "metalabel_v1_calibrator.pkl")
    joblib.dump(final_model, model_path)
    joblib.dump(iso, cal_path)
    
    # Report
    report = [
        "# Step 4 — Meta-labeler",
        f"**Date:** {datetime.now(IST).strftime('%Y-%m-%d')}",
        "",
        "## Configuration",
        f"- Base strategy: Variant D (30-min pure time)",
        f"- OOF period: 2023-2026",
        f"- Features: entry_conf, hour, mins_since_open, day_of_week, is_ce, consec_same_side",
        f"- Model: XGBoost binary, walk-forward by year",
        "",
        "## Cutoff Evaluation",
        f"Base trades: {base_n}, net PnL: {base_net:,.0f}",
        "",
        "| Cutoff | Trades | Retained% | Win% | Net PnL | PF |",
        "|--------|--------|-----------|------|---------|-----|",
    ]
    for cutoff in [0.0, 0.4, 0.5, 0.6]:
        fdf = df_eval if cutoff==0 else df_eval[df_eval["meta_score"]>=cutoff]
        n = len(fdf)
        if n==0: continue
        net = fdf["net_pnl"].sum()
        wr = (fdf["net_pnl"]>0).sum()/n*100
        gp = fdf[fdf["net_pnl"]>0]["net_pnl"].sum()
        gl = abs(fdf[fdf["net_pnl"]<=0]["net_pnl"].sum())
        pf = gp/gl if gl>0 else float('inf')
        report.append(f"| {cutoff} | {n} | {n/base_n*100:.0f}% | {wr:.0f}% | {net:,.0f} | {pf:.2f} |")
    
    rpath = os.path.join(REPORT_DIR, "step4_metalabel.md")
    with open(rpath, "w") as f:
        f.write("\n".join(report))
    print(f"\nReport -> {rpath}")
    print(f"Model -> {model_path}")

if __name__ == "__main__":
    main()
