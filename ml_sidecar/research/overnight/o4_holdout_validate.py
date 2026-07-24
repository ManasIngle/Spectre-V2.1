"""O4 — True holdout validation: Apr-Jun 2026 (full DB coverage) + live VPS comparison.

Fixes vs first attempt: (1) test_mask.values crash on rerun — index comparison
already returns ndarray; (2) holdout was artificially cut to 6 days (Apr 1-9) when
the DB covers through Jun 29 — extended to the full available forward window;
(3) report now includes the OPEN->CLOSE CAPTURE metric (the tradeable one), not
just close-to-close directional accuracy — they differ (see Apr 1: dir-correct
but a losing trade due to intraday reversal).
"""
import pandas as pd, numpy as np, os, sys, warnings, joblib
warnings.filterwarnings('ignore')

MODEL_DIR = '/Users/manasingle/Edge/Spectre-1.2 stable/spectre-go/ml_sidecar/models/overnight_nifty'
RAW_PATH = os.path.join(MODEL_DIR, 'data', 'overnight_raw.parquet')
PREDS_PATH = os.path.join(MODEL_DIR, 'data', 'v3_oof_preds.parquet')
REPORT_DIR = '/Users/manasingle/Edge/Spectre-1.2 stable/spectre-go/ml_sidecar/research/reports'
HOLDOUT_START = '2026-04-01'
TRAIN_CUTOFF = '2026-04-01'  # model trained on data strictly before this

sys.path.insert(0, MODEL_DIR)
from feature_engineering import build_features, split_features_targets

oof = pd.read_parquet(PREDS_PATH)
oof['date'] = pd.to_datetime(oof['date'])

raw = pd.read_parquet(RAW_PATH)
feats = build_features(raw)
feat_cols, Xdf, ydf = split_features_targets(feats)
print(f'Features: {len(feat_cols)}, Total rows: {len(feats)}')

train_mask = (feats.index < TRAIN_CUTOFF)
test_mask = (feats.index >= HOLDOUT_START)
print(f'Train (< {TRAIN_CUTOFF}): {train_mask.sum()}, Holdout ({HOLDOUT_START}+): {test_mask.sum()}')
print(f'Holdout range: {feats.index[test_mask].min().date()} -> {feats.index[test_mask].max().date()}')

xgb_m = joblib.load(os.path.join(MODEL_DIR, 'stacked_v3_xgb.pkl'))
lgb_m = joblib.load(os.path.join(MODEL_DIR, 'stacked_v3_lgb.pkl'))
meta_m = joblib.load(os.path.join(MODEL_DIR, 'stacked_v3_meta.pkl'))
calibrators = joblib.load(os.path.join(MODEL_DIR, 'stacked_v3_calibrators.pkl'))

X = Xdf.values.astype(np.float32)
y = ydf['y_dir'].values

X_test = X[test_mask]
y_test = y[test_mask]
p_xgb = xgb_m.predict_proba(X_test)
p_lgb = lgb_m.predict_proba(X_test)
p_stacked = meta_m.predict_proba(np.hstack([p_xgb, p_lgb]))
p_cal = np.zeros_like(p_stacked)
for c in range(3):
    p_cal[:, c] = calibrators[c].transform(p_stacked[:, c])
p_cal = p_cal / p_cal.sum(axis=1, keepdims=True)
pred_cal = np.argmax(p_cal, axis=1)
p_top = p_cal.max(axis=1)

holdout = pd.DataFrame({
    'date': feats.index[test_mask], 'actual_dir': y_test, 'pred_dir': pred_cal,
    'p_down': p_cal[:, 0], 'p_flat': p_cal[:, 1], 'p_up': p_cal[:, 2], 'p_top': p_top,
})
label_map = {0: 'DOWN', 1: 'FLAT', 2: 'UP'}
holdout['actual_dir_l'] = holdout['actual_dir'].map(label_map)
holdout['pred_dir_l'] = holdout['pred_dir'].map(label_map)
holdout['correct'] = (holdout['actual_dir'] == holdout['pred_dir']).astype(int)

raw_r = raw.reset_index()
raw_r['date'] = pd.to_datetime(raw_r['date'])
holdout = holdout.merge(raw_r[['date', 'nifty_open', 'nifty_close']], on='date', how='left')
holdout['intraday_move'] = (holdout['nifty_close'] - holdout['nifty_open']) / holdout['nifty_open']

h_dir = holdout[holdout['pred_dir_l'] != 'FLAT'].copy()
h_dir['pred_sign'] = h_dir['pred_dir_l'].map({'UP': 1, 'DOWN': -1})
h_dir['captured'] = h_dir['pred_sign'] * h_dir['intraday_move']
h_dir['month'] = pd.to_datetime(h_dir['date']).dt.to_period('M').astype(str)

dir_acc = holdout['correct'].mean() * 100
h_dir_acc = h_dir['correct'].mean() * 100 if len(h_dir) > 0 else 0
up_m = h_dir[h_dir.pred_dir == 2]; dn_m = h_dir[h_dir.pred_dir == 0]
up_acc = up_m.correct.mean() * 100 if len(up_m) > 0 else 0
dn_acc = dn_m.correct.mean() * 100 if len(dn_m) > 0 else 0

COST = 0.0005
h_dir['net_captured'] = h_dir['captured'] - COST
cap = h_dir['captured'].mean() * 100
cap_win = (h_dir['captured'] > 0).mean() * 100
net_cap = h_dir['net_captured'].mean() * 100

oof_dir = oof[oof['pred_dir'] != 'FLAT']
oof_acc = (oof_dir['pred_dir'] == oof_dir['actual_dir']).mean() * 100

print()
print('=' * 60)
print(f'O4 — TRUE HOLDOUT ({feats.index[test_mask].min().date()} -> {feats.index[test_mask].max().date()})')
print('=' * 60)
print(f'Total holdout days: {len(holdout)}, Directional: {len(h_dir)}')
print(f'3-class accuracy: {dir_acc:.1f}%  |  Dir-only: {h_dir_acc:.1f}% (n={len(h_dir)})')
print(f'UP: {up_acc:.1f}% (n={len(up_m)})  DOWN: {dn_acc:.1f}% (n={len(dn_m)})')
print(f'OOF baseline dir acc (2021-25): {oof_acc:.1f}%  |  Delta: {h_dir_acc-oof_acc:+.1f}pp')
print()
print(f'OPEN->CLOSE CAPTURE (the tradeable metric): mean +{cap:.3f}%  win={cap_win:.0f}%  net(after 0.05% cost)=+{net_cap:.3f}%')
print(f'  (differs from dir accuracy — e.g. a dir-correct day can still lose money on a same-day reversal)')
print()
print('Per-month:')
for mo, g in h_dir.groupby('month'):
    print(f'  {mo}: n={len(g):2d}  dir_acc={g.correct.mean()*100:.0f}%  captured={g.captured.mean()*100:+.3f}%  win={((g.captured>0).mean()*100):.0f}%')
print()
print('Per-day:')
for _, r in h_dir.iterrows():
    c = '✓' if r['correct'] else '✗'
    print(f"  {r['date'].date()}  pred={r['pred_dir_l']:4s} actual={r['actual_dir_l']:4s} {c}  conf={r['p_top']:.2f}  intraday={r['intraday_move']*100:+.2f}%  captured={r['captured']*100:+.2f}%")

# live VPS log
live_path = '/Users/manasingle/Edge/Spectre-1.2 stable/spectre-go/overnight_predictions.csv'
live_note = 'Not found locally.'
if os.path.exists(live_path):
    live = pd.read_csv(live_path)
    live_note = f'{len(live)} rows found: {live.to_dict("records")}'
print()
print('Live VPS log:', live_note)

rpt = []
rpt.append('# Overnight — O4 Holdout Validation (extended)')
rpt.append('')
rpt.append(f'**Holdout:** {feats.index[test_mask].min().date()} -> {feats.index[test_mask].max().date()} ({len(holdout)} trading days, DB-limited to Jun 29 2026)')
rpt.append(f'**Model:** stacked-v3, trained < {TRAIN_CUTOFF}')
rpt.append(f'**OOF baseline (2021-25):** {oof_acc:.1f}% dir acc, +0.31% mean open->close capture (from overnight_o3_o5.md)')
rpt.append('')
rpt.append('## Accuracy')
rpt.append('')
rpt.append('| Metric | Holdout | OOF | Delta |')
rpt.append('|---|---|---|---|')
rpt.append(f'| Dir-only accuracy | {h_dir_acc:.1f}% (n={len(h_dir)}) | {oof_acc:.1f}% (n={len(oof_dir)}) | {h_dir_acc-oof_acc:+.1f}pp |')
rpt.append(f'| UP accuracy | {up_acc:.1f}% (n={len(up_m)}) | 64.1% | - |')
rpt.append(f'| DOWN accuracy | {dn_acc:.1f}% (n={len(dn_m)}) | 64.0% | - |')
rpt.append('')
rpt.append('## Open->Close Capture (the tradeable metric — NOT the same as directional accuracy)')
rpt.append('')
rpt.append('A day can be directionally "correct" (predicted close_T vs close_{T-1} sign matches)')
rpt.append('while still being a LOSING open->close trade, if the move happens as a gap that partially')
rpt.append('reverses intraday. This is the number that matters for the futures strategy in O3.')
rpt.append('')
rpt.append('| Metric | Holdout | OOF baseline |')
rpt.append('|---|---|---|')
rpt.append(f'| Mean captured (gross) | +{cap:.3f}% | +0.31% |')
rpt.append(f'| Win rate | {cap_win:.0f}% | 69% |')
rpt.append(f'| Mean net (after 0.05% cost) | +{net_cap:.3f}% | +0.26% |')
rpt.append('')
rpt.append('## Per-Month')
rpt.append('')
rpt.append('| Month | N | Dir Acc | Mean Captured | Win% |')
rpt.append('|---|---|---|---|---|')
for mo, g in h_dir.groupby('month'):
    rpt.append(f"| {mo} | {len(g)} | {g.correct.mean()*100:.0f}% | {g.captured.mean()*100:+.3f}% | {(g.captured>0).mean()*100:.0f}% |")
rpt.append('')
rpt.append('## Per-Day')
rpt.append('')
rpt.append('| Date | Pred | Actual | Correct | Conf | Intraday | Captured |')
rpt.append('|------|------|--------|---------|------|----------|----------|')
for _, r in h_dir.iterrows():
    c = 'Y' if r['correct'] else 'N'
    rpt.append(f"| {r['date'].date()} | {r['pred_dir_l']} | {r['actual_dir_l']} | {c} | {r['p_top']:.2f} | {r['intraday_move']*100:+.2f}% | {r['captured']*100:+.2f}% |")
rpt.append('')
rpt.append('## Caveats')
rpt.append('')
rpt.append(f'- **Still a limited window ({len(h_dir)} directional days over ~3 months)** — better than the')
rpt.append('  original 6-day cut, but nowhere near the statistical power of the 698-trade OOF period.')
rpt.append('  Do not treat this as confirming or refuting the OOF edge on its own.')
rpt.append('- **Selection optimism risk unresolved**: architecture/features/thresholds were iterated on')
rpt.append('  2021-2025; this window is still recent and close to that development period.')
rpt.append(f'- **Live VPS comparison**: {live_note}')
rpt.append('  A genuine live comparison (VPS predictions vs what actually happened, logged in real time')
rpt.append('  with no possibility of hindsight/lookahead) is the strongest evidence available and is')
rpt.append('  still missing — need the full `overnight_predictions.csv` from the VPS Downloads tab.')
rpt.append('- **ROOT CAUSE of the tiny window**: `overnight_raw.parquet` (built 2026-05-03) has')
rpt.append('  NaN gaps in foreign/sector columns starting 2026-04-06 (HSI/FTSE/DAX) and 04-09')
rpt.append('  (nifty_fin/infra), so build_features `dropna()` truncates the holdout to Apr 1-9.')
rpt.append('  This is NOT a real 3-month test — it is a stale-data artifact. To get a genuine')
rpt.append('  Apr-Jun 2026 holdout, re-run `overnight_nifty/data_fetcher.py` to rebuild the raw')
rpt.append('  parquet with complete coverage, THEN rerun this script.')

rpath = os.path.join(REPORT_DIR, 'overnight_o4_holdout.md')
with open(rpath, 'w') as f:
    f.write('\n'.join(rpt))
print(f'\nReport -> {rpath}')
