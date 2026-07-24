import pandas as pd, numpy as np, os, sys, warnings
warnings.filterwarnings('ignore')

MODEL_DIR = '/Users/manasingle/Edge/Spectre-1.2 stable/spectre-go/ml_sidecar/models/overnight_nifty'
PREDS_PATH = os.path.join(MODEL_DIR, 'data', 'v3_oof_preds.parquet')
RAW_PATH = os.path.join(MODEL_DIR, 'data', 'overnight_raw.parquet')

preds = pd.read_parquet(PREDS_PATH)
raw = pd.read_parquet(RAW_PATH).reset_index()
preds['date'] = pd.to_datetime(preds['date'])
raw['date'] = pd.to_datetime(raw['date'])
merged = preds.merge(raw[['date','nifty_open','nifty_close']], on='date', how='inner')
merged['next_open'] = merged['nifty_open'].shift(-1)
merged['next_close'] = merged['nifty_close'].shift(-1)
merged = merged.iloc[:-1].copy()
tc = merged['nifty_close'].values; no = merged['next_open'].values; nc = merged['next_close'].values
merged['actual_close2close'] = (nc - tc) / tc * 100
merged['actual_open2close'] = (nc - no) / no * 100
merged['actual_gap'] = (no - tc) / tc * 100

dm = merged['pred_dir'] != 'FLAT'
d = merged[dm].copy()
d['pred_is_up'] = (d['pred_dir'] == 'UP').astype(int)
d['actual_is_up'] = (d['actual_dir'] == 'UP').astype(int)
d['correct'] = (d['pred_dir'] == d['actual_dir']).astype(int)
d['year'] = pd.to_datetime(d['date']).dt.year
d['p_top'] = merged.loc[dm, 'p_top'].values

print('='*60)
print('O1 — DIRECTIONAL SYMMETRY')
print('='*60)
print('Total OOF:', len(merged), 'Directional:', len(d), f'({len(d)/len(merged)*100:.0f}%)')
up = d[d.pred_is_up==1]; dn = d[d.pred_is_up==0]
print('When says UP:', f'{up.correct.mean()*100:.1f}%', 'n=', len(up))
print('When says DOWN:', f'{dn.correct.mean()*100:.1f}%', 'n=', len(dn))

print()
print('Per-year:')
for yr in sorted(d.year.unique()):
    dy = d[d.year==yr]; u = dy[dy.pred_is_up==1]; dn2 = dy[dy.pred_is_up==0]
    ua = u.correct.mean()*100 if len(u)>0 else 0
    da = dn2.correct.mean()*100 if len(dn2)>0 else 0
    print(f'{int(yr)}  tot={len(dy):3d}  UP: n={len(u):3d} acc={ua:.0f}%  DOWN: n={len(dn2):3d} acc={da:.0f}%')

print()
up_ct = d.actual_is_up.sum()
print('Baseline always-UP:', f'{up_ct/len(d)*100:.1f}%')
print('Model direction:', f'{d.correct.mean()*100:.1f}%')

print()
print('Conviction breakdown:')
for thr in [0.0,0.4,0.45,0.5,0.55,0.6,0.65]:
    s = d[d.p_top>=thr] if thr>0 else d
    if len(s)<5: continue
    u = s[s.pred_is_up==1]; dn3 = s[s.pred_is_up==0]
    ua = u.correct.mean()*100 if len(u)>0 else 0
    da = dn3.correct.mean()*100 if len(dn3)>0 else 0
    print(f'{thr:.2f}  n={len(s):3d} acc={s.correct.mean()*100:.0f}%  UP:n={len(u):3d} acc={ua:.0f}%  DOWN:n={len(dn3):3d} acc={da:.0f}%')

print()
print('='*60)
print('O2 — GAP DECOMPOSITION')
print('='*60)
ps = d.pred_dir.map({'UP':1,'DOWN':-1}).values
cer = ps * d.actual_close2close.values
oer = ps * d.actual_open2close.values
print('Mean captured return (n=', len(d), '):')
print('  Today-close entry:', f'{cer.mean()*100:.3f}%')
print('  Next-open entry:  ', f'{oer.mean()*100:.3f}%')
print('  Gap component:    ', f'{d.actual_gap.abs().mean()*100:.3f}%')

print()
print('By conviction (today-close entry):')
for thr in [0.0,0.4,0.45,0.5,0.55,0.6,0.65]:
    m = d.p_top.values>=thr if thr>0 else np.ones(len(d),dtype=bool)
    if m.sum()<5: continue
    r = cer[m]; wr = (r>0).mean()*100; ac = d.iloc[m].correct.mean()*100
    print(f'{thr:.2f}  n={m.sum():3d}  ret={r.mean()*100:.3f}%  win={wr:.0f}%  acc={ac:.0f}%')

print()
print('By conviction (next-open entry):')
for thr in [0.0,0.4,0.45,0.5,0.55,0.6,0.65]:
    m = d.p_top.values>=thr if thr>0 else np.ones(len(d),dtype=bool)
    if m.sum()<5: continue
    r = oer[m]; wr = (r>0).mean()*100; ac = d.iloc[m].correct.mean()*100
    print(f'{thr:.2f}  n={m.sum():3d}  ret={r.mean()*100:.3f}%  win={wr:.0f}%  acc={ac:.0f}%')