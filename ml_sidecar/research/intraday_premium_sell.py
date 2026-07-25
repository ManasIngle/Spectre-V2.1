"""Intraday premium-selling test — sell ATM straddle in predicted-CALM windows.

Hypothesis: the strong volatility signal (low ATR% -> 0.5% move rate) lets us sell
a straddle and collect theta when we're confident the market won't move.
Gate: enter only when recent ATR% is low (calm). Hold 60 min, buy back.
P&L via BS (VIX=IV). Realistic double-leg spread applied.

HONEST CAVEAT baked into interpretation: constant-IV BS is OPTIMISTIC for premium
selling — it cannot see IV spikes / gap-driven vega losses that actually blow up
short-vol books. So if this LOSES even under BS, it's decisively dead. If it wins,
that win is an upper bound needing real-option validation.
"""
import pandas as pd, numpy as np
from scipy.stats import norm

df = pd.read_parquet('ml_sidecar/research/data/training_v2.parquet')
df['date'] = df.index.date
df['minofday'] = df.index.hour * 60 + df.index.minute
HOLD = 60  # minutes
close = df['close'].values
vixarr = df['feat_vix_level'].clip(8, 60).values / 100.0
atr = df['feat_volatility'].values

# exit price = close HOLD minutes later, same day
df['exit_close'] = df.groupby('date')['close'].shift(-HOLD)
exit_close = df['exit_close'].values
valid = ~np.isnan(exit_close)

TTE = 2 / 365.0
def bs_vec(S, K, T, iv, call):
    T = np.maximum(T, 1e-6); iv = np.maximum(iv, 1e-6)
    d1 = (np.log(S / K) + (0.065 + 0.5 * iv**2) * T) / (iv * np.sqrt(T))
    d2 = d1 - iv * np.sqrt(T)
    if call:
        return S * norm.cdf(d1) - K * np.exp(-0.065 * T) * norm.cdf(d2)
    return K * np.exp(-0.065 * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

K = np.round(close / 50) * 50
straddle_in = bs_vec(close, K, TTE, vixarr, True) + bs_vec(close, K, TTE, vixarr, False)
tte_out = TTE - HOLD / (365 * 24 * 60)
straddle_out = bs_vec(exit_close, K, tte_out, vixarr, True) + bs_vec(exit_close, K, tte_out, vixarr, False)
# SHORT straddle: profit = entry - exit (premium decayed) ; loss if it expanded
short_pnl = straddle_in - straddle_out  # option points, gross

d = pd.DataFrame({'date': df['date'].values, 'atr': atr, 'vix': df['feat_vix_level'].values,
                  'mind': df['minofday'].values, 'sin': straddle_in, 'sout': straddle_out,
                  'pnl': short_pnl})[valid & (straddle_in > 1.0)]

print(f"Intraday SHORT-straddle, hold {HOLD}min, {len(d):,} entry bars\n")
print(f"{'calm gate':>16} {'n':>7} {'grossPnL':>9} {'win%':>6}  netPnL @ per-leg spread")
print(f"{'':>16} {'':>7} {'(pts)':>9} {'':>6}   0.5%     1%      2%")
print('-' * 70)
for lbl, mask in [('ALL (no gate)', np.ones(len(d), bool)),
                  ('ATR%<0.10', d.atr < 0.10),
                  ('ATR%<0.08', d.atr < 0.08),
                  ('ATR%<0.06 (calm)', d.atr < 0.06),
                  ('ATR%<0.06 & VIX<14', (d.atr < 0.06) & (d.vix < 14))]:
    s = d[mask]
    if len(s) < 50:
        print(f"{lbl:>16} {len(s):>7}  too few"); continue
    gross = s.pnl.mean()
    # cost: 4 leg-crossings (sell 2 + buy 2), each half-spread on ~ (straddle/2) per leg
    cells = []
    for leg in [0.005, 0.01, 0.02]:
        cost = leg * (s.sin + s.sout)  # ~full-spread on entry+exit straddle notional
        net = (s.pnl - cost).mean()
        cells.append(f"{net:+6.2f}")
    print(f"{lbl:>16} {len(s):>7} {gross:>+8.2f} {(s.pnl>0).mean()*100:>5.0f}%  {cells[0]}  {cells[1]}  {cells[2]}")

print("\nnet = mean option-pts per trade (x65 lot for Rs). Positive after spread = worth real-option test.")
print("Tail check (the risk that blows up sellers):")
for lbl, mask in [('ATR%<0.06', d.atr < 0.06)]:
    s = d[mask]
    print(f"  {lbl}: worst trade {s.pnl.min():+.1f} pts | 1%%-tail {s.pnl.quantile(0.01):+.1f} | mean {s.pnl.mean():+.2f} | this is BS (no IV-spike) -> real tails worse")
