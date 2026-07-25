"""Intraday horizon sweep — does directional predictability improve at ANY cadence?

Prior test found AUC 0.52 at the 30-min horizon. This sweeps 5/10/15/20/30/45/60 min
to answer: is there a timeframe where the model can call the direction of a
tradeable-size move (~40 index pts ≈ 0.17%)?

Two questions per horizon:
  Q1 (direction): GIVEN a >=thr move happens, can we predict its sign? -> move-only 2-class AUC
  Q2 (frequency): how often does a >=thr move happen in h minutes? (signal cadence)

Features: price/technical only (clock features EXCLUDED — they're time-of-day
base-rate lookups that don't generalize, as shown in Step 3b). Strict time split.
"""
import pandas as pd, numpy as np
import xgboost as xgb
from sklearn.metrics import roc_auc_score

df = pd.read_parquet('ml_sidecar/research/data/training_v2.parquet')
df['date'] = df.index.date
CLOCK = {'feat_hour', 'feat_day_of_week', 'feat_minutes_since_open', 'feat_session_position'}
feats = [c for c in df.columns if c.startswith('feat_') and c not in CLOCK]
print(f'{len(feats)} price/technical features (clock excluded), {len(df):,} rows\n')

close = df['close']
# forward return at horizon h, within-day only (NaN across day boundary)
def fwd_ret(h):
    r = close.shift(-h) / close - 1.0
    same_day = df['date'].values == pd.Series(df['date']).shift(-h).values
    r = r.where(same_day)
    return r * 100  # percent

HORIZONS = [5, 10, 15, 20, 30, 45, 60]
THRESHOLDS = [0.10, 0.15, 0.20]  # % move; 0.17% ~= 40 pts at 24000

XGB = dict(n_estimators=250, max_depth=6, learning_rate=0.05, subsample=0.8,
           colsample_bytree=0.8, min_child_weight=5, random_state=42, n_jobs=-1,
           verbosity=0, eval_metric='logloss')

print(f"{'horizon':>7} {'thr%':>5} {'move_freq':>9} {'n_moves':>8} {'DIR_AUC':>8}  verdict")
print('-'*54)
X_all = df[feats].values
for thr in THRESHOLDS:
    for h in HORIZONS:
        r = fwd_ret(h).values
        mv = np.abs(r) >= thr
        mask = mv & ~np.isnan(r)
        n = mask.sum()
        freq = n / (~np.isnan(r)).sum() * 100
        # move-only 2-class: 1=UP move, 0=DOWN move
        Xm = X_all[mask]; ym = (r[mask] > 0).astype(int)
        cut = int(len(Xm) * 0.7)
        if cut < 500 or len(Xm) - cut < 200:
            print(f"{h:>6}m {thr:>5.2f} {freq:>8.1f}% {n:>8} {'--too few--':>8}")
            continue
        m = xgb.XGBClassifier(**XGB)
        m.fit(Xm[:cut], ym[:cut])
        p = m.predict_proba(Xm[cut:])[:, 1]
        auc = roc_auc_score(ym[cut:], p)
        v = 'EDGE?' if auc >= 0.55 else ('weak' if auc >= 0.53 else 'noise')
        print(f"{h:>6}m {thr:>5.2f} {freq:>8.1f}% {n:>8} {auc:>8.4f}  {v}")
    print()
print('Reference: AUC 0.50 = coin flip; ~0.55+ needed to have any chance after costs.')
