"""
Spectre v1.2 — Optimal Hold Time Finder
----------------------------------------
For EVERY signal in the CSV, compute Nifty P&L at t+1, t+2, ... t+30 minutes.
Find the optimal hold duration that maximizes cumulative returns.
"""

import csv
from collections import defaultdict
from datetime import datetime, timedelta

CSV_PATH = "/Users/manasingle/Downloads/ml_trade_logs-till-13-04-26.csv"
MAX_HOLD = 30  # minutes

def load_rows():
    with open(CSV_PATH) as f:
        return list(csv.DictReader(f))

def parse_time(date_str, time_str):
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")

def run():
    rows = load_rows()

    # Build per-day spot series: date -> [(datetime, spot)]
    daily_spots = defaultdict(list)
    for row in rows:
        dt = parse_time(row["Date"], row["Time"])
        daily_spots[row["Date"]].append((dt, float(row["Spot"])))
    for d in daily_spots:
        daily_spots[d].sort()

    # For fast lookup: date -> {minute_key -> spot}
    # minute_key = minutes since midnight
    daily_spot_map = {}
    for date, spots in daily_spots.items():
        spot_map = {}
        for dt, spot in spots:
            key = dt.hour * 60 + dt.minute
            spot_map[key] = spot  # last value wins for that minute
        daily_spot_map[date] = spot_map

    # Process every signal
    # hold_pnl[t] = list of P&L values at hold time t minutes
    hold_pnl = defaultdict(list)
    # Also track by confidence bucket
    conf_hold_pnl = defaultdict(lambda: defaultdict(list))
    # Track by signal type
    sig_hold_pnl = defaultdict(lambda: defaultdict(list))

    total_signals = 0
    skipped = 0

    for row in rows:
        sig = row["Signal"]
        if sig == "NO TRADE":
            continue

        date = row["Date"]
        dt = parse_time(date, row["Time"])
        entry_spot = float(row["Spot"])
        conf = float(row["Confidence"])
        is_bullish = sig == "BUY CE"

        spot_map = daily_spot_map.get(date, {})
        entry_min = dt.hour * 60 + dt.minute
        market_close_min = 15 * 60 + 30  # 15:30

        total_signals += 1

        for t in range(1, MAX_HOLD + 1):
            target_min = entry_min + t
            if target_min > market_close_min:
                break

            # Find nearest available spot at target_min
            # Check exact minute, then ±1 minute
            exit_spot = None
            for offset in [0, -1, 1]:
                if (target_min + offset) in spot_map:
                    exit_spot = spot_map[target_min + offset]
                    break

            if exit_spot is None:
                continue

            if is_bullish:
                pnl = exit_spot - entry_spot
            else:
                pnl = entry_spot - exit_spot

            hold_pnl[t].append(pnl)

            # Bucket by confidence
            if conf < 40:
                bucket = "35-40%"
            elif conf < 45:
                bucket = "40-45%"
            elif conf < 50:
                bucket = "45-50%"
            elif conf < 55:
                bucket = "50-55%"
            elif conf < 60:
                bucket = "55-60%"
            else:
                bucket = "60%+"
            conf_hold_pnl[bucket][t].append(pnl)
            sig_hold_pnl[sig][t].append(pnl)

    # Print results
    print("=" * 85)
    print("  SPECTRE v1.2 — OPTIMAL HOLD TIME ANALYSIS")
    print(f"  Total signals processed: {total_signals}")
    print(f"  Date range: {rows[0]['Date']} to {rows[-1]['Date']}")
    print("=" * 85)

    print(f"\n{'─' * 85}")
    print(f"  ALL SIGNALS — P&L at each hold duration")
    print(f"{'─' * 85}")
    print(f"  {'Hold':>5}  {'Trades':>7}  {'Avg P&L':>9}  {'Total P&L':>11}  {'Win%':>6}  {'Avg Win':>8}  {'Avg Loss':>9}  {'Chart'}")
    print(f"  {'min':>5}  {'':>7}  {'(pts)':>9}  {'(pts)':>11}  {'':>6}  {'(pts)':>8}  {'(pts)':>9}")

    best_avg = -999
    best_t = 0
    best_total = -999999
    best_total_t = 0

    for t in range(1, MAX_HOLD + 1):
        vals = hold_pnl.get(t, [])
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        total = sum(vals)
        wins = [v for v in vals if v > 0]
        losses = [v for v in vals if v <= 0]
        win_pct = len(wins) / len(vals) * 100
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0

        bar_len = int(avg * 3) if avg > 0 else int(avg * 3)
        if avg > 0:
            bar = "█" * min(bar_len, 30)
            chart = f"  🟢 {bar}"
        else:
            bar = "█" * min(abs(bar_len), 30)
            chart = f"  🔴 {bar}"

        marker = ""
        if avg > best_avg:
            best_avg = avg
            best_t = t
        if total > best_total:
            best_total = total
            best_total_t = t

        print(f"  {t:>4}m  {len(vals):>7}  {avg:>+9.2f}  {total:>+11.1f}  {win_pct:>5.1f}%  {avg_win:>+8.2f}  {avg_loss:>+9.2f}{chart}")

    print(f"\n  >>> BEST avg P&L/trade: {best_t} min ({best_avg:+.2f} pts)")
    print(f"  >>> BEST total P&L:     {best_total_t} min ({best_total:+.1f} pts)")

    # By confidence bucket
    bucket_order = ["35-40%", "40-45%", "45-50%", "50-55%", "55-60%", "60%+"]
    for bucket in bucket_order:
        data = conf_hold_pnl.get(bucket)
        if not data:
            continue
        print(f"\n{'─' * 85}")
        print(f"  CONFIDENCE: {bucket}")
        print(f"{'─' * 85}")
        print(f"  {'Hold':>5}  {'Trades':>7}  {'Avg P&L':>9}  {'Total P&L':>11}  {'Win%':>6}  {'Chart'}")

        b_best_avg = -999
        b_best_t = 0
        for t in range(1, MAX_HOLD + 1):
            vals = data.get(t, [])
            if not vals:
                continue
            avg = sum(vals) / len(vals)
            total = sum(vals)
            wins = [v for v in vals if v > 0]
            win_pct = len(wins) / len(vals) * 100
            bar_len = int(avg * 3)
            if avg > 0:
                chart = f"  🟢 {'█' * min(bar_len, 30)}"
            else:
                chart = f"  🔴 {'█' * min(abs(bar_len), 30)}"
            if avg > b_best_avg:
                b_best_avg = avg
                b_best_t = t
            print(f"  {t:>4}m  {len(vals):>7}  {avg:>+9.2f}  {total:>+11.1f}  {win_pct:>5.1f}%{chart}")

        print(f"  >>> BEST: {b_best_t} min ({b_best_avg:+.2f} pts/trade)")

    # BUY CE vs BUY PE
    for sig in ["BUY CE", "BUY PE"]:
        data = sig_hold_pnl.get(sig)
        if not data:
            continue
        print(f"\n{'─' * 85}")
        print(f"  SIGNAL: {sig}")
        print(f"{'─' * 85}")
        print(f"  {'Hold':>5}  {'Trades':>7}  {'Avg P&L':>9}  {'Total P&L':>11}  {'Win%':>6}  {'Chart'}")

        s_best_avg = -999
        s_best_t = 0
        for t in range(1, MAX_HOLD + 1):
            vals = data.get(t, [])
            if not vals:
                continue
            avg = sum(vals) / len(vals)
            total = sum(vals)
            wins = [v for v in vals if v > 0]
            win_pct = len(wins) / len(vals) * 100
            bar_len = int(avg * 3)
            if avg > 0:
                chart = f"  🟢 {'█' * min(bar_len, 30)}"
            else:
                chart = f"  🔴 {'█' * min(abs(bar_len), 30)}"
            if avg > s_best_avg:
                s_best_avg = avg
                s_best_t = t
            print(f"  {t:>4}m  {len(vals):>7}  {avg:>+9.2f}  {total:>+11.1f}  {win_pct:>5.1f}%{chart}")

        print(f"  >>> BEST: {s_best_t} min ({s_best_avg:+.2f} pts/trade)")

    # Summary table
    print(f"\n{'=' * 85}")
    print(f"  OPTIMAL HOLD TIME SUMMARY")
    print(f"{'=' * 85}")
    print(f"  {'Category':<20} {'Best Hold':>10} {'Avg P&L':>10} {'Win%':>8}")
    print(f"  {'─'*20} {'─'*10} {'─'*10} {'─'*8}")

    # All signals
    t = best_t
    vals = hold_pnl[t]
    wp = len([v for v in vals if v > 0]) / len(vals) * 100
    print(f"  {'ALL SIGNALS':<20} {t:>8}m  {best_avg:>+9.2f} {wp:>7.1f}%")

    for bucket in bucket_order:
        data = conf_hold_pnl.get(bucket)
        if not data:
            continue
        b_best_avg = -999
        b_best_t = 0
        for tt in range(1, MAX_HOLD + 1):
            vals = data.get(tt, [])
            if vals and sum(vals)/len(vals) > b_best_avg:
                b_best_avg = sum(vals)/len(vals)
                b_best_t = tt
        if b_best_t and data.get(b_best_t):
            vals = data[b_best_t]
            wp = len([v for v in vals if v > 0]) / len(vals) * 100
            print(f"  {'Conf ' + bucket:<20} {b_best_t:>8}m  {b_best_avg:>+9.2f} {wp:>7.1f}%")

    for sig in ["BUY CE", "BUY PE"]:
        data = sig_hold_pnl.get(sig)
        if not data:
            continue
        s_best_avg = -999
        s_best_t = 0
        for tt in range(1, MAX_HOLD + 1):
            vals = data.get(tt, [])
            if vals and sum(vals)/len(vals) > s_best_avg:
                s_best_avg = sum(vals)/len(vals)
                s_best_t = tt
        if s_best_t and data.get(s_best_t):
            vals = data[s_best_t]
            wp = len([v for v in vals if v > 0]) / len(vals) * 100
            print(f"  {sig:<20} {s_best_t:>8}m  {s_best_avg:>+9.2f} {wp:>7.1f}%")

    print()

if __name__ == "__main__":
    run()
