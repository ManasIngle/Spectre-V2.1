"""
Spectre v1.2 Signal Backtest
----------------------------
Reads ml_trade_logs CSV, deduplicates signals (1 per 5-min window),
and checks if Nifty hit Target or SL first using subsequent spot prices.
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta

CSV_PATH = "/Users/manasingle/Downloads/ml_trade_logs-till-13-04-26.csv"

def load_rows():
    with open(CSV_PATH) as f:
        return list(csv.DictReader(f))

def parse_time(date_str, time_str):
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")

def run_backtest(min_conf=0.0, sample_interval_min=5, max_hold_min=60):
    rows = load_rows()

    # Group by date and build minute-level spot price series
    daily_spots = defaultdict(list)  # date -> [(datetime, spot), ...]
    for row in rows:
        dt = parse_time(row["Date"], row["Time"])
        spot = float(row["Spot"])
        daily_spots[row["Date"]].append((dt, spot))

    # Sort each day's spots
    for d in daily_spots:
        daily_spots[d].sort()

    # Sample signals: one per 5-min window per day
    signals = []
    last_signal_time = {}

    for row in rows:
        sig = row["Signal"]
        if sig == "NO TRADE":
            continue

        conf = float(row["Confidence"])
        if conf < min_conf:
            continue

        dt = parse_time(row["Date"], row["Time"])
        date = row["Date"]

        # Deduplicate: skip if we had a signal within sample_interval_min
        key = date
        if key in last_signal_time:
            if (dt - last_signal_time[key]).total_seconds() < sample_interval_min * 60:
                continue

        last_signal_time[key] = dt
        signals.append({
            "date": date,
            "time": dt,
            "signal": sig,
            "prediction": row["Prediction"],
            "confidence": conf,
            "spot": float(row["Spot"]),
            "strike": float(row["Strike"]),
            "option_type": row["OptionType"],
            "option_ltp": float(row["Option_LTP"]) if row["Option_LTP"] not in ("", "N/A", "None") else None,
            "target": float(row["Target"]),
            "sl": float(row["SL"]),
        })

    # Backtest each signal
    results = []
    for sig in signals:
        spots = daily_spots[sig["date"]]
        entry_time = sig["time"]
        max_hold_end = entry_time + timedelta(minutes=max_hold_min)
        market_close = entry_time.replace(hour=15, minute=30, second=0)
        deadline = min(max_hold_end, market_close)

        target = sig["target"]
        sl = sig["sl"]
        entry_spot = sig["spot"]
        is_bullish = sig["signal"] == "BUY CE"

        outcome = "EXPIRED"
        exit_spot = entry_spot
        exit_time = deadline
        hold_mins = 0

        for (t, spot) in spots:
            if t <= entry_time:
                continue
            if t > deadline:
                # Use last known spot as exit
                break

            if is_bullish:
                if spot >= target:
                    outcome = "WIN"
                    exit_spot = spot
                    exit_time = t
                    break
                elif spot <= sl:
                    outcome = "LOSS"
                    exit_spot = spot
                    exit_time = t
                    break
            else:  # BUY PE (bearish)
                if spot <= target:
                    outcome = "WIN"
                    exit_spot = spot
                    exit_time = t
                    break
                elif spot >= sl:
                    outcome = "LOSS"
                    exit_spot = spot
                    exit_time = t
                    break

            exit_spot = spot
            exit_time = t

        hold_mins = (exit_time - entry_time).total_seconds() / 60

        # Nifty points P&L
        if is_bullish:
            nifty_pnl = exit_spot - entry_spot
        else:
            nifty_pnl = entry_spot - exit_spot

        results.append({
            **sig,
            "outcome": outcome,
            "exit_spot": exit_spot,
            "nifty_pnl": nifty_pnl,
            "hold_mins": hold_mins,
        })

    return signals, results


def print_report(signals, results, label=""):
    if label:
        print(f"\n{'='*70}")
        print(f"  {label}")
        print(f"{'='*70}")

    total = len(results)
    if total == 0:
        print("No signals to backtest.")
        return

    wins = [r for r in results if r["outcome"] == "WIN"]
    losses = [r for r in results if r["outcome"] == "LOSS"]
    expired = [r for r in results if r["outcome"] == "EXPIRED"]

    win_rate = len(wins) / total * 100
    avg_pnl = sum(r["nifty_pnl"] for r in results) / total
    total_pnl = sum(r["nifty_pnl"] for r in results)
    avg_hold = sum(r["hold_mins"] for r in results) / total

    avg_win_pnl = sum(r["nifty_pnl"] for r in wins) / len(wins) if wins else 0
    avg_loss_pnl = sum(r["nifty_pnl"] for r in losses) / len(losses) if losses else 0

    # Risk-reward ratio
    rr = abs(avg_win_pnl / avg_loss_pnl) if avg_loss_pnl != 0 else 0

    # Max drawdown (cumulative)
    cumulative = []
    running = 0
    peak = 0
    max_dd = 0
    for r in results:
        running += r["nifty_pnl"]
        cumulative.append(running)
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    # By signal type
    ce_results = [r for r in results if r["signal"] == "BUY CE"]
    pe_results = [r for r in results if r["signal"] == "BUY PE"]
    ce_wins = sum(1 for r in ce_results if r["outcome"] == "WIN")
    pe_wins = sum(1 for r in pe_results if r["outcome"] == "WIN")

    # Daily breakdown
    daily_pnl = defaultdict(float)
    daily_trades = defaultdict(int)
    for r in results:
        daily_pnl[r["date"]] += r["nifty_pnl"]
        daily_trades[r["date"]] += 1
    green_days = sum(1 for v in daily_pnl.values() if v > 0)
    red_days = sum(1 for v in daily_pnl.values() if v <= 0)

    # By confidence bucket
    buckets = {"35-40%": (35, 40), "40-45%": (40, 45), "45-50%": (45, 50),
               "50-55%": (50, 55), "55-60%": (55, 60), "60%+": (60, 100)}

    print(f"\n--- SUMMARY ---")
    print(f"  Total signals (sampled):  {total}")
    print(f"  Date range:               {results[0]['date']} to {results[-1]['date']}")
    print(f"  Trading days:             {len(daily_pnl)}")
    print(f"")
    print(f"  Wins:     {len(wins):>4}  ({win_rate:.1f}%)")
    print(f"  Losses:   {len(losses):>4}  ({len(losses)/total*100:.1f}%)")
    print(f"  Expired:  {len(expired):>4}  ({len(expired)/total*100:.1f}%)")
    print(f"")
    print(f"  Avg P&L per trade:  {avg_pnl:+.1f} Nifty pts")
    print(f"  Total P&L:          {total_pnl:+.1f} Nifty pts")
    print(f"  Avg win:            {avg_win_pnl:+.1f} pts")
    print(f"  Avg loss:           {avg_loss_pnl:+.1f} pts")
    print(f"  Risk:Reward:        1:{rr:.2f}")
    print(f"  Max Drawdown:       {max_dd:.1f} pts")
    print(f"  Avg hold time:      {avg_hold:.0f} min")
    print(f"")
    print(f"  BUY CE:  {len(ce_results)} trades, {ce_wins} wins ({ce_wins/len(ce_results)*100:.1f}%)" if ce_results else "")
    print(f"  BUY PE:  {len(pe_results)} trades, {pe_wins} wins ({pe_wins/len(pe_results)*100:.1f}%)" if pe_results else "")
    print(f"")
    print(f"  Green days: {green_days}  |  Red days: {red_days}")
    print(f"")

    print(f"--- DAILY BREAKDOWN ---")
    for date in sorted(daily_pnl.keys()):
        pnl = daily_pnl[date]
        n = daily_trades[date]
        marker = "+" if pnl > 0 else " "
        bar = "█" * int(abs(pnl) / 5) if abs(pnl) > 0 else ""
        color_bar = f"  {'🟢' if pnl > 0 else '🔴'} {bar}"
        print(f"  {date}  {marker}{pnl:>8.1f} pts  ({n:>2} trades){color_bar}")
    print()

    print(f"--- CONFIDENCE BUCKETS ---")
    print(f"  {'Bucket':<10} {'Trades':>7} {'Win%':>7} {'Avg P&L':>10} {'Total':>10}")
    for label, (lo, hi) in buckets.items():
        bucket = [r for r in results if lo <= r["confidence"] < hi]
        if not bucket:
            continue
        bwins = sum(1 for r in bucket if r["outcome"] == "WIN")
        bpnl = sum(r["nifty_pnl"] for r in bucket)
        bavg = bpnl / len(bucket)
        print(f"  {label:<10} {len(bucket):>7} {bwins/len(bucket)*100:>6.1f}% {bavg:>+9.1f} {bpnl:>+9.1f}")
    print()


if __name__ == "__main__":
    print("=" * 70)
    print("  SPECTRE v1.2 — HISTORICAL SIGNAL BACKTEST")
    print("  Data: ml_trade_logs Mar 12 - Apr 13, 2026")
    print("=" * 70)

    # Run multiple scenarios
    for conf_filter, hold in [(0, 60), (40, 60), (45, 60), (50, 60), (55, 60)]:
        sigs, res = run_backtest(min_conf=conf_filter, sample_interval_min=5, max_hold_min=hold)
        print_report(sigs, res, label=f"Conf >= {conf_filter}% | Max Hold: {hold} min | 5-min sampling")
