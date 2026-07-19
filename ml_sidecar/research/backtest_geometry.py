#!/usr/bin/env python3
"""
Step 2 — Exit-geometry & filter backtest (6.5 years, honest costs).
Event-driven on minute bars, consuming Step 1 signals. Black-Scholes
premium model, 4 variants (A/B/C/D), net-of-costs reporting.
"""
import os, sys, json, sqlite3, time as time_mod, gc, warnings
import numpy as np
import pandas as pd
import joblib
from scipy.stats import norm
from datetime import datetime, timedelta
import zoneinfo
warnings.filterwarnings("ignore")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_DIR = os.path.join(ROOT_DIR, "ml_sidecar", "models")
RESEARCH_DIR = os.path.join(ROOT_DIR, "ml_sidecar", "research")
DATA_DIR = os.path.join(RESEARCH_DIR, "data")
REPORT_DIR = os.path.join(RESEARCH_DIR, "reports")
DB_PATH = "/Users/manasingle/Edge/June/Miequity/archive_2020_smart.db"
VER = "-Rtr14April"
ROLLING_MODEL = os.path.join(MODEL_DIR, f"nifty_rolling_model{VER}.pkl")
DIRECTION_MODEL = os.path.join(MODEL_DIR, f"nifty_direction_model_5m{VER}.pkl")
METADATA_PATH = os.path.join(MODEL_DIR, f"model_metadata_5m{VER}.json")
IST = zoneinfo.ZoneInfo("Asia/Kolkata")
LOT_SIZE = 65
BROKERAGE = 25.0
SLIPPAGE_BPS = 5.0
RISK_FREE_RATE = 0.065
CONF_THRESHOLD = 35

def bs_price(spot, strike, tte_years, iv, opt_type, r=RISK_FREE_RATE):
    if tte_years <= 0 or iv <= 0 or strike <= 0:
        return 0.0
    d1 = (np.log(spot/strike) + (r + iv**2/2) * tte_years) / (iv * np.sqrt(tte_years))
    d2 = d1 - iv * np.sqrt(tte_years)
    if opt_type == "CE":
        return spot * norm.cdf(d1) - strike * np.exp(-r * tte_years) * norm.cdf(d2)
    else:
        return strike * np.exp(-r * tte_years) * norm.cdf(-d2) - spot * norm.cdf(-d1)

def nearest_weekly_thursday(dt):
    d = dt.date()
    while d.weekday() != 3:
        d += timedelta(days=1)
    if dt.date() == d and dt.time() >= datetime.strptime("15:30","%H:%M").time():
        d += timedelta(days=7)
    elif d < dt.date():
        d += timedelta(days=7)
    return datetime.combine(d, datetime.strptime("15:30","%H:%M").time(), tzinfo=IST)

def compute_premium(spot, strike, dt, vix):
    tte = (nearest_weekly_thursday(dt) - dt).total_seconds() / (365*24*3600)
    if tte <= 0:
        tte = 1.0/365
    return bs_price(spot, strike, tte, vix/100.0, "CE"), bs_price(spot, strike, tte, vix/100.0, "PE")

def atm_strike(spot):
    return round(spot / 50) * 50

def trade_strike(spot, opt_type, conf):
    atm = atm_strike(spot)
    if conf > 45:
        return atm
    return atm + 50 if opt_type == "CE" else atm - 50

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

def compute_atr(df_1m, period=14):
    h, l, c = df_1m["High"].values, df_1m["Low"].values, df_1m["Close"].values
    tr = np.maximum(h-l, np.maximum(abs(h-np.roll(c,1)), abs(l-np.roll(c,1))))
    tr[0] = h[0]-l[0]
    atr = np.zeros_like(tr)
    atr[0] = tr[0]
    for i in range(1, len(tr)):
        atr[i] = (atr[i-1]*(period-1)+tr[i])/period
    return pd.Series(atr, index=df_1m.index)

def generate_signals_for_range(date_start, date_end):
    """Generate replay signals using day-anchored buffers."""
    sys.path.insert(0, os.path.join(RESEARCH_DIR))
    from replay import _extract_features, build_rolling_bar
    
    start_dt = int(date_start + "000000")
    end_dt = int(date_end + "235959")
    
    nifty_df = load_1m_bars(9, start_dt, end_dt)
    vix_series = load_1m_bars(6, start_dt, end_dt)["Close"]
    
    rolling_model = joblib.load(ROLLING_MODEL)
    direction_model = joblib.load(DIRECTION_MODEL)
    with open(METADATA_PATH) as f:
        feature_cols = json.load(f)["feature_columns"]
    
    dates = sorted(set(nifty_df.index.date))
    daily_dfs = []
    for day_date in dates:
        day_mask = nifty_df.index.date == day_date
        day_nifty = nifty_df[day_mask]
        day_vix = vix_series[vix_series.index.date == day_date]
        
        bars_buffer, vix_buffer, results = [], [], []
        for ts, row in day_nifty.iterrows():
            bars_buffer.append([row["Close"],row["High"],row["Low"],row["Open"],row["Volume"]])
            if ts in day_vix.index and pd.notna(day_vix.loc[ts]):
                vix_buffer.append(day_vix.loc[ts])
            elif vix_buffer:
                vix_buffer.append(vix_buffer[-1])
            else:
                vix_buffer.append(16.0)
            
            X, _ = _extract_features(bars_buffer, feature_cols, ts, vix_closes=list(vix_buffer))
            if X is None:
                continue
            
            rp = rolling_model.predict_proba(X)[0]
            dp = direction_model.predict_proba(X)[0]
            probs = [(r+d)/2 for r,d in zip(rp,dp)]
            pred = int(np.argmax(probs))
            conf = probs[pred]*100
            
            signal = "NO TRADE"
            if conf > CONF_THRESHOLD:
                if pred == 2: signal = "BUY CE"
                elif pred == 0: signal = "BUY PE"
            
            results.append({
                "dt": ts, "nifty_close": row["Close"],
                "vix_close": vix_buffer[-1],
                "pred": pred, "conf": round(conf,1), "signal": signal,
                "prob_down": round(probs[0]*100,1),
                "prob_side": round(probs[1]*100,1),
                "prob_up": round(probs[2]*100,1),
            })
        if results:
            daily_dfs.append(pd.DataFrame(results).set_index("dt"))
        gc.collect()
    
    return pd.concat(daily_dfs).sort_index() if daily_dfs else pd.DataFrame()

class BacktestResult:
    def __init__(self):
        self.trades = []

def run_backtest(nifty_df, vix_series, signals_df, atr_series,
                 timeout_min=9, target_atr=2.0, sl_atr=1.0,
                 conf_threshold=35, skip_hours=None, entry_after_min=30):
    """Event-driven backtest. Returns BacktestResult."""
    result = BacktestResult()
    skip_hours = skip_hours or set()
    position = None
    
    for i, (ts, row) in enumerate(nifty_df.iterrows()):
        spot = row["Close"]
        vix = vix_series.loc[ts] if ts in vix_series.index else 16.0
        atr = atr_series.loc[ts] if ts in atr_series.index else atr_series.iloc[max(0,i-1)]
        min_of_day = ts.hour * 60 + ts.minute
        
        # Exit check
        if position is not None:
            held_mins = i - position["entry_idx"]
            exit_reason = None
            e_ce, e_pe = compute_premium(spot, position["strike"], ts, vix)
            exit_p = e_ce if position["opt_type"]=="CE" else e_pe
            
            if min_of_day >= 15*60+15:
                exit_reason = "EOD"
            elif held_mins >= timeout_min:
                exit_reason = "TIMEOUT"
            elif target_atr > 0 and sl_atr > 0:
                if position["opt_type"] == "CE":
                    if spot >= position["target_spot"]: exit_reason = "TARGET"
                    elif spot <= position["sl_spot"]: exit_reason = "SL"
                else:
                    if spot <= position["target_spot"]: exit_reason = "TARGET"
                    elif spot >= position["sl_spot"]: exit_reason = "SL"
            
            if exit_reason:
                ep = position["entry_premium"]
                gross = (exit_p - ep) * LOT_SIZE
                slip_in = ep * SLIPPAGE_BPS/10000 * LOT_SIZE
                slip_out = exit_p * SLIPPAGE_BPS/10000 * LOT_SIZE
                net = gross - BROKERAGE - slip_in - slip_out
                result.trades.append(dict(
                    entry_ts=position["entry_ts"], exit_ts=ts,
                    opt_type=position["opt_type"], strike=position["strike"],
                    entry_spot=position["entry_spot"], exit_spot=spot,
                    entry_premium=ep, exit_premium=exit_p,
                    held_mins=held_mins, exit_reason=exit_reason,
                    gross_pnl=round(gross,2), net_pnl=round(net,2),
                    entry_conf=position["entry_conf"],
                    entry_hour=position["entry_ts"].hour,
                    entry_signal=position["entry_signal"]))
                position = None
        
        # Entry logic
        if position is not None:
            continue
        mins_since_open = (ts.hour-9)*60 + ts.minute - 15
        if mins_since_open < entry_after_min: continue
        if min_of_day >= 15*60: continue
        if ts.hour in skip_hours: continue
        if ts not in signals_df.index: continue
        
        sig = signals_df.loc[ts]
        if sig.get("signal","NO TRADE") not in ("BUY CE","BUY PE"): continue
        conf = sig.get("conf",0)
        if conf <= conf_threshold: continue
        
        opt_type = "CE" if sig["signal"]=="BUY CE" else "PE"
        strike = trade_strike(spot, opt_type, conf)
        e_ce, e_pe = compute_premium(spot, strike, ts, vix)
        entry_p = e_ce if opt_type=="CE" else e_pe
        if entry_p <= 0: continue
        
        tgt = spot + atr*target_atr if opt_type=="CE" else spot - atr*target_atr
        sl = spot - atr*sl_atr if opt_type=="CE" else spot + atr*sl_atr
        
        position = dict(opt_type=opt_type, strike=strike, entry_spot=spot,
                        entry_premium=entry_p, entry_idx=i, entry_ts=ts,
                        target_spot=tgt, sl_spot=sl, entry_conf=conf,
                        entry_signal=sig["signal"])
    
    # Close any open position at end
    if position is not None:
        ts = nifty_df.index[-1]; spot = nifty_df.iloc[-1]["Close"]
        vix = vix_series.iloc[-1] if len(vix_series)>0 else 16.0
        e_ce, e_pe = compute_premium(spot, position["strike"], ts, vix)
        ep, exit_p = position["entry_premium"], (e_ce if position["opt_type"]=="CE" else e_pe)
        gross = (exit_p - ep) * LOT_SIZE
        slip_in = ep * SLIPPAGE_BPS/10000 * LOT_SIZE
        slip_out = exit_p * SLIPPAGE_BPS/10000 * LOT_SIZE
        net = gross - BROKERAGE - slip_in - slip_out
        result.trades.append(dict(
            entry_ts=position["entry_ts"], exit_ts=ts,
            opt_type=position["opt_type"], strike=position["strike"],
            entry_spot=position["entry_spot"], exit_spot=spot,
            entry_premium=ep, exit_premium=exit_p,
            held_mins=len(nifty_df)-position["entry_idx"],
            exit_reason="EOD", gross_pnl=round(gross,2), net_pnl=round(net,2),
            entry_conf=position["entry_conf"],
            entry_hour=position["entry_ts"].hour,
            entry_signal=position["entry_signal"]))
    
    return result

def compute_metrics(trades, label=""):
    if not trades:
        return {"label": label, "n_trades": 0, "gross_pnl": 0, "net_pnl": 0}
    df = pd.DataFrame(trades)
    days = len(set(t["entry_ts"].date() for t in trades))
    wins = df[df["net_pnl"] > 0]
    losses = df[df["net_pnl"] <= 0]
    
    gross = df["gross_pnl"].sum()
    net = df["net_pnl"].sum()
    n = len(df)
    win_rate = len(wins)/n*100 if n>0 else 0
    expectancy = net/n if n>0 else 0
    avg_win = wins["net_pnl"].mean() if len(wins)>0 else 0
    avg_loss = losses["net_pnl"].mean() if len(losses)>0 else 0
    gross_profit = wins["net_pnl"].sum() if len(wins)>0 else 0
    gross_loss = abs(losses["net_pnl"].sum()) if len(losses)>0 else 0.01
    pf = gross_profit/gross_loss
    cum = df["net_pnl"].cumsum()
    max_dd = (cum - cum.cummax()).min()
    exit_dist = df["exit_reason"].value_counts().to_dict()
    
    return {
        "label": label, "n_trades": n, "trading_days": days,
        "trades_per_day": n/days if days>0 else 0,
        "gross_pnl": round(gross,2), "net_pnl": round(net,2),
        "win_rate": round(win_rate,1), "pf": round(pf,2),
        "expectancy": round(expectancy,2),
        "avg_win": round(avg_win,2), "avg_loss": round(avg_loss,2),
        "max_dd": round(max_dd,2), "exit_dist": exit_dist
    }

VARIANTS = {
    "A":  {"timeout": 9,  "target_atr": 2.0, "sl_atr": 1.0, "skip_hours": set(),   "conf": 35},
    "B":  {"timeout": 30, "target_atr": 1.0, "sl_atr": 1.0, "skip_hours": set(),   "conf": 35},
    "C35":{"timeout": 30, "target_atr": 1.0, "sl_atr": 1.0, "skip_hours": {11},    "conf": 35},
    "C40":{"timeout": 30, "target_atr": 1.0, "sl_atr": 1.0, "skip_hours": {11},    "conf": 40},
    "C45":{"timeout": 30, "target_atr": 1.0, "sl_atr": 1.0, "skip_hours": {11},    "conf": 45},
    "D":  {"timeout": 30, "target_atr": 0.0, "sl_atr": 0.0, "skip_hours": set(),   "conf": 35},
}

def run_all_variants(nifty_df, vix_series, signals_df, atr_series, window_label=""):
    results = {}
    for vname, vcfg in VARIANTS.items():
        bt = run_backtest(nifty_df, vix_series, signals_df, atr_series,
                          timeout_min=vcfg["timeout"], target_atr=vcfg["target_atr"],
                          sl_atr=vcfg["sl_atr"], conf_threshold=vcfg["conf"],
                          skip_hours=vcfg["skip_hours"])
        m = compute_metrics(bt.trades, f"{vname} {window_label}".strip())
        if bt.trades:
            edf = pd.DataFrame(bt.trades)
            m["exit_dist"] = edf["exit_reason"].value_counts().to_dict()
            m["hourly"] = edf.groupby("entry_hour").agg(
                n=("net_pnl","count"), net=("net_pnl","sum"),
                win_rate=("net_pnl",lambda x: (x>0).mean()*100)).to_dict()
            edf["cb"] = (edf["entry_conf"]//5)*5
            m["conf_buckets"] = edf.groupby("cb").agg(
                n=("net_pnl","count"), net=("net_pnl","sum"),
                win_rate=("net_pnl",lambda x: (x>0).mean()*100)).to_dict()
        results[vname] = m
        print(f"  {vname}: {m['n_trades']} trades, net {m['net_pnl']:,.0f}, PF {m['pf']:.2f}, win {m['win_rate']:.1f}%")
    return results

def fmt_table(results, title):
    lines = [f"\n### {title}", "",
             "| V | Trades | Gross | Net | Exp/tr | Win% | PF | Max DD | T/day |",
             "|---|--------|-------|------|---------|------|-----|--------|-------|"]
    for v in VARIANTS:
        m = results.get(v,{})
        if not m or m.get("n_trades",0)==0:
            lines.append(f"| {v} | 0 | 0 | 0 | 0 | - | - | 0 | 0 |")
        else:
            lines.append(f"| {v} | {m['n_trades']} | {m['gross_pnl']:,.0f} | {m['net_pnl']:,.0f} | {m['expectancy']:,.0f} | {m['win_rate']:.0f}% | {m['pf']:.2f} | {m['max_dd']:,.0f} | {m['trades_per_day']:.1f} |")
    return "\n".join(lines)

def fmt_exits(results):
    lines = ["\n### Exit Reasons", "",
             "| V | TARGET | SL | TIMEOUT | EOD |",
             "|---|--------|-----|---------|-----|"]
    for v in VARIANTS:
        ed = results.get(v,{}).get("exit_dist",{})
        lines.append(f"| {v} | {ed.get('TARGET',0)} | {ed.get('SL',0)} | {ed.get('TIMEOUT',0)} | {ed.get('EOD',0)} |")
    return "\n".join(lines)

def main():
    import argparse
    p = argparse.ArgumentParser(description="Step 2: Geometry backtest")
    p.add_argument("--full-only", action="store_true")
    p.add_argument("--anchor-only", action="store_true")
    args = p.parse_args()
    
    os.makedirs(REPORT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    
    full_start, full_end = "20200101", "20260629"
    anchor_start, anchor_end = "20260428", "20260629"
    
    report = [
        "# Step 2 — Geometry & Exit Backtest",
        f"**Date:** {datetime.now(IST).strftime('%Y-%m-%d')}",
        "",
        "## Configuration",
        f"Lot: {LOT_SIZE} | Brokerage: {BROKERAGE}/trade | Slippage: {SLIPPAGE_BPS}bps/side | r={RISK_FREE_RATE*100:.1f}%",
        "IV proxy: VIX/100 (Black-Scholes approx) | Premiums recomputed each minute",
        "Entry gate: after 09:30, before 15:00 | Close all by 15:15 | One position at a time",
        "",
        "### Variants",
        "| V | Timeout | Target | SL | Skip Hr | Conf |",
        "|---|---------|--------|-----|---------|------|",
    ]
    for vname, vcfg in VARIANTS.items():
        tgt = f"{vcfg['target_atr']}xATR" if vcfg['target_atr']>0 else "none"
        sl = f"{vcfg['sl_atr']}xATR" if vcfg['sl_atr']>0 else "none"
        report.append(f"| {vname} | {vcfg['timeout']}m | {tgt} | {sl} | {vcfg['skip_hours'] or 'none'} | {vcfg['conf']} |")
    
    if not args.anchor_only:
        print("Loading full-period data (2020-2026)...")
        nifty_f = load_1m_bars(9, int(full_start+"000000"), int(full_end+"235959"))
        vix_f = load_1m_bars(6, int(full_start+"000000"), int(full_end+"235959"))
        vix_fs = vix_f["Close"] if len(vix_f)>0 else pd.Series(dtype=float)
        print(f"  Nifty: {len(nifty_f):,} bars")
        
        sig_cache = os.path.join(DATA_DIR, f"signals_{full_start}_{full_end}.csv")
        if os.path.exists(sig_cache):
            print("Loading cached signals")
            signals_f = pd.read_csv(sig_cache, index_col=0, parse_dates=True)
        else:
            print("Generating signals (6.5 years)...")
            all_sigs = []
            for yr in range(2020,2027):
                print(f"  Year {yr}...")
                ys = generate_signals_for_range(f"{yr}0101",f"{yr}1231")
                if len(ys)>0: all_sigs.append(ys)
                gc.collect()
            signals_f = pd.concat(all_sigs).sort_index()
            signals_f.to_csv(sig_cache)
            print(f"  {len(signals_f):,} signals cached")
        
        atr_f = compute_atr(nifty_f)
        print("Running full-period backtest...")
        res_f = run_all_variants(nifty_f, vix_fs, signals_f, atr_f, "full")
        report.append("\n## Full Period (2020-01-01 -> 2026-06-29)")
        report.append(fmt_table(res_f, "Summary"))
        report.append(fmt_exits(res_f))
    
    if not args.full_only:
        print(f"\nLoading anchor data ({anchor_start} -> {anchor_end})...")
        nifty_a = load_1m_bars(9, int(anchor_start+"000000"), int(anchor_end+"235959"))
        vix_a = load_1m_bars(6, int(anchor_start+"000000"), int(anchor_end+"235959"))
        vix_as = vix_a["Close"] if len(vix_a)>0 else pd.Series(dtype=float)
        
        sig_cache_a = os.path.join(DATA_DIR, f"signals_{anchor_start}_{anchor_end}.csv")
        if os.path.exists(sig_cache_a):
            signals_a = pd.read_csv(sig_cache_a, index_col=0, parse_dates=True)
        else:
            signals_a = generate_signals_for_range(anchor_start, anchor_end)
            signals_a.to_csv(sig_cache_a)
        
        atr_a = compute_atr(nifty_a)
        print(f"Running anchor backtest ({len(signals_a):,} signals)...")
        res_a = run_all_variants(nifty_a, vix_as, signals_a, atr_a, "anchor")
        report.append(f"\n## Anchor Period ({anchor_start} -> {anchor_end})")
        report.append("> Comparison: 78-day live log (SL>>TARGET, ~breakeven clean sample)")
        report.append(fmt_table(res_a, "Summary"))
        report.append(fmt_exits(res_a))
    
    rpath = os.path.join(REPORT_DIR, "step2_geometry.md")
    with open(rpath, "w") as f:
        f.write("\n".join(report))
    print(f"\nReport -> {rpath}")

if __name__ == "__main__":
    main()
