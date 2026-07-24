"""O4 — True holdout validation: Apr-Jun 2026 + live VPS comparison."""
import pandas as pd, numpy as np, os, sys, warnings, json, joblib
import lightgbm as lgb
import xgboost as xgb
warnings.filterwarnings('ignore')

MODEL_DIR = '/Users/manasingle/Edge/Spectre-1.2 stable/spectre-go/ml_sidecar/models/overnight_nifty'
RAW_PATH = os.path.join(MODEL_DIR, 'data', 'overnight_raw.parquet')
PREDS_PATH = os.path.join(MODEL_DIR, 'data', 'v3_oof_preds.parquet')
REPORT_DIR = '/Users/manasingle/Edge/Spectre-1.2 stable/spectre-go/ml_sidecar/research/reports'

sys.path.insert(0, MODEL_DIR)
from feature_engineering import build_features, split_features_targets

# Load OOF baseline
oof = pd.read_parquet(PREDS_PATH)
oof['date'] = pd.to_datetime(oof['date'])

# Load holdout data
raw = pd.read_parquet(RAW_PATH)
feats = build_features(raw)
feat_cols, Xdf, ydf = split_features_targets(feats)
print(f'Features: {len(feat_cols)}, Total rows: {len(feats)}')

# Split holdout: Apr 2026
train_mask = feats.index < '2026-04-01'
test_mask = feats.index >= '2026-04-01'
print(f'Train (<=Mar 2026): {train_mask.sum()}, Holdout (Apr+): {test_mask.sum()}')

# Load saved models
xgb_m = joblib.load(os.path.join(MODEL_DIR, 'stacked_v3_xgb.pkl'))
lgb_m = joblib.load(os.path.join(MODEL_DIR, 'stacked_v3_lgb.pkl'))
meta_m = joblib.load(os.path.join(MODEL_DIR, 'stacked_v3_meta.pkl'))
calibrators = joblib.load(os.path.join(MODEL_DIR, 'stacked_v3_calibrators.pkl'))

X = Xdf.values.astype(np.float32)
y = ydf['y_dir'].values

# Generate holdout predictions via stacked pipeline
X_test = X[test_mask.values]
y_test = y[test_mask.values]
p_xgb = xgb_m.predict_proba(X_test)
p_lgb = lgb_m.predict_proba(X_test)
p_stacked = meta_m.predict_proba(np.hstack([p_xgb, p_lgb]))
p_cal = np.zeros_like(p_stacked)
for c in range(3):
    p_cal[:, c] = calibrators[c].transform(p_stacked[:, c])
p_cal = p_cal / p_cal.sum(axis=1, keepdims=True)
pred_cal = np.argmax(p_cal, axis=1)
p_top = p_cal.max(axis=1)

# Build holdout results DataFrame
holdout = pd.DataFrame({
    'date': feats.index[test_mask],
    'actual_dir': y_test,
    'pred_dir': pred_cal,
    'p_down': p_cal[:, 0],
    'p_flat': p_cal[:, 1],
    'p_up': p_cal[:, 2],
    'p_top': p_top,
})
label_map = {0: 'DOWN', 1: 'FLAT', 2: 'UP'}
holdout['actual_dir_l'] = holdout['actual_dir'].map(label_map)
holdout['pred_dir_l'] = holdout['pred_dir'].map(label_map)
holdout['correct'] = (holdout['actual_dir'] == holdout['pred_dir']).astype(int)

# Merge with price data for open->close capture
raw_r = raw.reset_index()
raw_r['date'] = pd.to_datetime(raw_r['date'])
holdout = holdout.merge(raw_r[['date','nifty_open','nifty_close']], on='date', how='left')
holdout['intraday_move'] = (holdout['nifty_close'] - holdout['nifty_open']) / holdout['nifty_open']

# Directional subset
h_dir = holdout[holdout['pred_dir_l'] != 'FLAT'].copy()
h_dir['pred_sign'] = h_dir['pred_dir_l'].map({'UP': 1, 'DOWN': -1})
h_dir['captured'] = h_dir['pred_sign'] * h_dir['intraday_move']

print()
print('='*60)
print('O4 — TRUE HOLDOUT (Apr 2026)')
print('='*60)
print(f'Total holdout days: {len(holdout)}')
print(f'Directional: {len(h_dir)}')
print(f'Actual UP base rate: {(holdout.actual_dir==2).sum()/len(holdout)*100:.0f}%')

dir_acc = holdout['correct'].mean()*100
h_dir_acc = h_dir['correct'].mean()*100 if len(h_dir)>0 else 0
up_m = h_dir[h_dir.pred_dir==2]; dn_m = h_dir[h_dir.pred_dir==0]
up_acc = up_m.correct.mean()*100 if len(up_m)>0 else 0
dn_acc = dn_m.correct.mean()*100 if len(dn_m)>0 else 0
print(f'3-class accuracy: {dir_acc:.1f}%')
print(f'Dir-only: {h_dir_acc:.1f}% (n={len(h_dir)})')
print(f'UP: {up_acc:.1f}% (n={len(up_m)}), DOWN: {dn_acc:.1f}% (n={len(dn_m)})')

print()
print('Open->Close capture (directional):')
cap = h_dir['captured'].mean()*100
cap_win = (h_dir['captured']>0).mean()*100
print(f'Mean captured: +{cap:.3f}%')
print(f'Win rate: {cap_win:.0f}%')

print()
print('Comparison vs OOF baseline:')
oof_dir = oof[oof['pred_dir']!='FLAT']
oof_acc = (oof_dir['pred_dir']==oof_dir['actual_dir']).mean()*100
print(f'  OOF dir accuracy (2021-25): {oof_acc:.1f}%')
print(f'  Holdout dir accuracy:       {h_dir_acc:.1f}%')
print(f'  Delta: {h_dir_acc - oof_acc:+.1f}pp')

print()
print('Per-day predictions:')
for _, r in holdout.iterrows():
    corr = '✓' if r['correct'] else '✗'
    print(f"  {r['date'].date()}  pred={r['pred_dir_l']:4s}  actual={r['actual_dir_l']:4s}  {corr}  intraday={r['intraday_move']*100:+.2f}%")

# Report
rpt = []
rpt.append('# Overnight — O4 Holdout Validation')
rpt.append('')
rpt.append(f'**Holdout:** April 2026 ({len(holdout)} trading days)')
rpt.append(f'**Model:** stacked-v3, trained <= 2026-03-31')
rpt.append(f'**OOF baseline:** 2021-2025, n={len(oof_dir)} directional, {oof_acc:.1f}% dir acc')
rpt.append('')
rpt.append('## Accuracy')
rpt.append('')
rpt.append(f'| Metric | Holdout | OOF | Delta |')
rpt.append(f'|---|---|---|---|')
rpt.append(f'| 3-class | {dir_acc:.1f}% | - | - |')
rpt.append(f'| Dir-only | {h_dir_acc:.1f}% | {oof_acc:.1f}% | {h_dir_acc-oof_acc:+.1f}pp |')
rpt.append(f'| UP | {up_acc:.1f}% (n={len(up_m)}) | - | - |')
rpt.append(f'| DOWN | {dn_acc:.1f}% (n={len(dn_m)}) | - | - |')
rpt.append('')
rpt.append('## Open->Close Capture')
rpt.append('')
rpt.append(f'| Metric | Holdout | OOF baseline |')
rpt.append(f'|---|---|---|')
rpt.append(f'| Mean captured | +{cap:.3f}% | +0.31% (expected) |')
rpt.append(f'| Win rate | {cap_win:.0f}% | 69% (expected) |')
rpt.append('')
rpt.append('## Per-Day')
rpt.append('')
rpt.append('| Date | Pred | Actual | Correct | Intraday |')
rpt.append('|------|------|--------|---------|----------|')
for _, r in holdout.iterrows():
    corr = '✓' if r['correct'] else '✗'
    rpt.append(f"| {r['date'].date()} | {r['pred_dir_l']} | {r['actual_dir_l']} | {corr} | {r['intraday_move']*100:+.2f}% |")

rpt.append('')
rpt.append('## Live VPS Comparison')
rpt.append('')
rpt.append('The live overnight endpoint has been logging predictions. Only 1 row found in overnight_predictions.csv (Apr 25: predicted DOWN, actual pending). Full live comparison requires the VPS prediction log — if available, append here.')

rpath = os.path.join(REPORT_DIR, 'overnight_o4_holdout.md')
with open(rpath, 'w') as f:
    f.write('\n'.join(rpt))
print(f'\nReport -> {rpath}')