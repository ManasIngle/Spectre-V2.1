#!/usr/bin/env python3
"""O3 — Money test: equity curve for the overnight-signal / intraday-futures strategy.
Strategy: on each directional prediction (dated T, known ~03:30 IST), enter Nifty
FUTURES at open_T in the predicted direction, exit at close_T. No overnight gap risk.

O5 (calibration honesty) is folded in: the conf=0 book (all directional trades) is
calibration-INDEPENDENT and is the primary result. Conviction-filtered books are
shown as upside, with an explicit accuracy haircut applied, because the OOF
confidences were isotonic-calibrated in-sample (~5pp optimistic per DECISION.md).
"""
import pandas as pd, numpy as np, os

MD = os.path.join(os.path.dirname(__file__), '..', '..', 'models', 'overnight_nifty', 'data')
preds = pd.read_parquet(os.path.join(MD, 'v3_oof_preds.parquet'))
raw = pd.read_parquet(os.path.join(MD, 'overnight_raw.parquet')).reset_index()
preds['date'] = pd.to_datetime(preds['date']); raw['date'] = pd.to_datetime(raw['date'])
m = preds.merge(raw[['date', 'nifty_open', 'nifty_close']], on='date', how='inner')
d = m[m['pred_dir'] != 'FLAT'].copy()
d['year'] = d['date'].dt.year
ps = d['pred_dir'].map({'UP': 1, 'DOWN': -1}).values
d['gross'] = ps * (d['nifty_close'].values - d['nifty_open'].values) / d['nifty_open'].values  # decimal, open->close

# Realistic Nifty futures round-trip cost on notional (STT 0.02% sell + txn/GST/stamp
# ~0.01% + brokerage ~0.002% + open-fill slippage ~0.03%). Base 0.05%; sensitivity shown.
COST = 0.0005

def book(sub, cost=COST, acc_haircut=0.0):
    """Return stats for a set of trades. acc_haircut shifts a fraction of wins->losses
    to model calibration optimism (only used for conf-filtered books)."""
    r = sub['gross'].values.copy()
    if acc_haircut > 0:
        # flip the acc_haircut fraction of correct trades to their mirror loss (conservative)
        correct = sub['correct'].values.astype(bool)
        n_flip = int(round(acc_haircut * len(r)))
        idx = np.where(correct)[0]
        rng = np.random.default_rng(42)
        flip = rng.choice(idx, size=min(n_flip, len(idx)), replace=False)
        r[flip] = -np.abs(r[flip])
    net = r - cost
    eq = np.cumsum(net)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak)
    n = len(net)
    wins = net[net > 0]; losses = net[net < 0]
    pf = wins.sum() / -losses.sum() if losses.sum() != 0 else np.inf
    tpy = n / 5.0  # ~5-year OOF; annualize by actual trades/year, not 252
    sharpe = net.mean() / net.std() * np.sqrt(tpy) if net.std() > 0 else 0
    return dict(n=n, gross_mean=r.mean()*100, net_mean=net.mean()*100, net_total=net.sum()*100,
                win=(net > 0).mean()*100, pf=pf, maxdd=dd.min()*100, sharpe=sharpe,
                per_yr=sub.assign(net=net).groupby('year')['net'].sum()*100)

d['correct'] = (d['pred_dir'] == d['actual_dir']).astype(int)

print("="*70)
print("O3 — EQUITY CURVE (Nifty futures, open->close, cost=%.2f%% round-trip)" % (COST*100))
print("="*70)
print("Sum-of-returns equity in %% of notional per 1-lot trade. Return-on-margin ~5x (futures ~20%% margin).\n")

books = {
    "conf=0  (ALL directional — calibration-free, PRIMARY)": (d, 0.0),
    "conf>=0.55 (raw)": (d[d.p_top >= 0.55], 0.0),
    "conf>=0.55 (5pp haircut)": (d[d.p_top >= 0.55], 0.05),
    "conf>=0.60 (raw)": (d[d.p_top >= 0.60], 0.0),
    "conf>=0.60 (5pp haircut)": (d[d.p_top >= 0.60], 0.05),
}
rows = []
for name, (sub, hc) in books.items():
    b = book(sub, acc_haircut=hc)
    rows.append((name, b))
    print(f"{name}")
    print(f"   n={b['n']:3d}  net/trade=+{b['net_mean']:.3f}%  total=+{b['net_total']:.1f}%  "
          f"win={b['win']:.0f}%  PF={b['pf']:.2f}  maxDD={b['maxdd']:.1f}%  Sharpe~{b['sharpe']:.2f}")
    print(f"   per-year net%: " + "  ".join(f"{y}:{v:+.1f}" for y, v in b['per_yr'].items()))
    print()

print("Cost sensitivity (conf=0 book), net total % of notional:")
for c in [0.0003, 0.0005, 0.0008]:
    b = book(d, cost=c)
    print(f"   cost {c*100:.2f}%%: net/trade +{b['net_mean']:.3f}%  total +{b['net_total']:.1f}%  PF {b['pf']:.2f}")

# rupee illustration
LOT_NOTIONAL = 20_00_000  # ~1 Nifty futures lot notional (illustrative)
b0 = book(d)
print(f"\nRupee illustration (1 lot ~Rs {LOT_NOTIONAL:,} notional, conf=0, {b0['n']} trades/5y):")
print(f"   +{b0['net_mean']:.3f}%/trade on notional = ~Rs {b0['net_mean']/100*LOT_NOTIONAL:,.0f}/trade")
print(f"   5-year total ~Rs {b0['net_total']/100*LOT_NOTIONAL:,.0f} on notional (return-on-margin ~5x)")
