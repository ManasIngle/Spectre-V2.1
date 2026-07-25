"""Intraday 5-min signal — realistic option-cost money test (the make-or-break gate).

Honest design (avoids the traps that sank earlier work):
- Direction model trained on move-only bars, but APPLIED TO ALL TEST BARS (no
  look-ahead on which bars had moves). Signal = top-confidence bars among ALL bars.
  This simultaneously tests the "is a move coming?" gate: if high-confidence bars
  don't actually move, the long option just bleeds the spread.
- Option P&L via Black-Scholes on the ATM (~0.5 delta) option, repriced after the
  5-min hold with the realized spot move. Real bid-ask spread applied (1-3%).
- Walk-forward by year. Lot 65.
"""
import pandas as pd, numpy as np
import xgboost as xgb
from scipy.stats import norm

df = pd.read_parquet('ml_sidecar/research/data/training_v2.parquet')
df['date'] = df.index.date; df['year'] = df.index.year
CLOCK = {'feat_hour', 'feat_day_of_week', 'feat_minutes_since_open', 'feat_session_position'}
feats = [c for c in df.columns if c.startswith('feat_') and c not in CLOCK]
close = df['close']; vix = df['feat_vix_level'].clip(8, 60)

H, THR = 5, 0.15
r = (close.shift(-H) / close - 1.0)
sd = df['date'].values == pd.Series(df['date']).shift(-H).values
df['fwd'] = (r.where(sd) * 100)  # % 5-min forward return, within-day
df['exit_spot'] = close.shift(-H).where(sd)

def bs(S, K, T, iv, typ):
    if T <= 0 or iv <= 0: return max(0.0, (S-K) if typ=='C' else (K-S))
    d1 = (np.log(S/K) + (0.065 + 0.5*iv**2)*T) / (iv*np.sqrt(T))
    d2 = d1 - iv*np.sqrt(T)
    if typ == 'C': return S*norm.cdf(d1) - K*np.exp(-0.065*T)*norm.cdf(d2)
    return K*np.exp(-0.065*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

XGB = dict(n_estimators=250, max_depth=6, learning_rate=0.05, subsample=0.8,
           colsample_bytree=0.8, min_child_weight=5, random_state=42, n_jobs=-1,
           verbosity=0, eval_metric='logloss')

# Walk-forward: train direction (move-only) on <yr, predict ALL bars of =yr
valid = df['fwd'].notna() & df['exit_spot'].notna()
d = df[valid].copy(); d['fwd_dec'] = d['fwd']/100
X = d[feats].values
move = np.abs(d['fwd'].values) >= THR
y_up = (d['fwd'].values > 0).astype(int)
oof_p = np.full(len(d), np.nan)
yrs = sorted(d['year'].unique())
for i in range(2, len(yrs)):
    tr_all = (d['year'] < yrs[i]).values; te = (d['year'] == yrs[i]).values
    tr = tr_all & move  # train on move bars only
    if tr.sum() < 2000: continue
    m = xgb.XGBClassifier(**XGB); m.fit(X[tr], y_up[tr])
    oof_p[te] = m.predict_proba(X[te])[:, 1]  # applied to ALL test bars
d['p_up'] = oof_p
t = d[d['p_up'].notna()].copy()
t['conf'] = np.abs(t['p_up'] - 0.5)
TTE = 2/365.0  # representative weekly time-to-expiry

def option_pnl(row, spread):
    S, Sx, iv = row['close'], row['exit_spot'], row['feat_vix_level']/100
    typ = 'C' if row['p_up'] > 0.5 else 'P'
    K = round(S/50)*50
    ent = bs(S, K, TTE, iv, typ)
    ex = bs(Sx, K, TTE - H/(365*24*60), iv, typ)
    if ent <= 0.5: return np.nan  # skip near-zero premium (illiquid deep OTM)
    gross = ex - ent
    cost = spread * ent  # round-trip bid-ask on premium
    return gross - cost

print("Intraday 5-min signal, option money test (ATM ~0.5delta, walk-forward OOF)")
print(f"n bars scored={len(t):,}  |  TTE={TTE*365:.0f}d  |  lot=65\n")
print(f"{'filter':>10} {'n':>6} {'dir_hit%':>8} {'move_rate%':>10}  net option pts/trade @ spread")
print(f"{'':>10} {'':>6} {'':>8} {'':>10}   1%      2%      3%")
print('-'*72)
for q, lbl in [(0,'all'),(50,'top50%'),(75,'top25%'),(90,'top10%'),(95,'top5%'),(98,'top2%')]:
    thr_c = np.percentile(t['conf'], q)
    s = t[t['conf'] >= thr_c].copy()
    moved = np.abs(s['fwd'].values) >= THR
    # dir hit among moved bars only (direction is only defined when there's a move)
    hit = ((s['p_up']>0.5).astype(int).values[moved] == (s['fwd'].values[moved]>0).astype(int)).mean()*100 if moved.sum()>0 else 0
    cells = []
    for sp in [0.01, 0.02, 0.03]:
        pnl = s.apply(lambda rr: option_pnl(rr, sp), axis=1)
        cells.append(f"{pnl.mean():+6.2f}")
    print(f"{lbl:>10} {len(s):>6} {hit:>7.1f}% {moved.mean()*100:>9.1f}%  {cells[0]}  {cells[1]}  {cells[2]}")
print("\nnet pts/trade = mean option-point P&L per signal (ALL signal bars incl. non-movers).")
print("x65 for rupees. Positive after 2-3% spread = genuinely tradeable.")
