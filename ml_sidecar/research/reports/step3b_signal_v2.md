# Step 3b — Signal Model v2
**Date:** 2026-07-22

## Configuration
- Rows: 488,962 | Features: 30 | Folds: 9
- Dropped: ['feat_day_of_week', 'feat_equity_advance_pct', 'feat_equity_momentum', 'feat_equity_weighted_ret', 'feat_hour', 'feat_minutes_since_open', 'feat_session_position']
- Labels: DOWN=115,599 SIDE=251,607 UP=121,756
- Calibration: causal (subprocess-per-fold)
- Time: 32s

## Overall OOF
| | Before | After |
|---|---|---|
| F1 macro | 0.2783 | 0.2647 |
| Brier | 0.1927 | - |

## Top 10 Features
| R | Feature | Imp |
|---|---|---|
| 1 | feat_volatility | 0.2437 |
| 2 | feat_vix_regime | 0.2248 |
| 3 | feat_vix_level | 0.0660 |
| 4 | feat_futures_premium_proxy | 0.0288 |
| 5 | feat_slow_rsi | 0.0285 |
| 6 | feat_ema_spread | 0.0253 |
| 7 | feat_vix_vs_avg | 0.0234 |
| 8 | feat_close_ma_dev | 0.0229 |
| 9 | feat_ret_1 | 0.0227 |
| 10 | feat_ret_3 | 0.0222 |

## Causal Calibration
| Bucket | N | Acc |
|--------|---|-----|
| 30-35 | 4,449 | 34.6% |
| 35-40 | 38,170 | 38.2% |
| 40-45 | 49,913 | 43.8% |
| 45-50 | 43,813 | 48.8% |
| 50-55 | 34,336 | 55.5% |
| 55-60 | 47,284 | 58.8% |
| 60-65 | 57,223 | 63.5% |
| 65-70 | 46,208 | 68.7% |
| 70-75 | 12,625 | 71.3% |
| 75-80 | 1,091 | 76.9% |
| 80-85 | 514 | 76.1% |
| 85-90 | 143 | 80.4% |
| 90-95 | 177 | 63.3% |
| 95-100 | 357 | 71.1% |

## ATR Vendor-Robustness
| Perturb | F1 | Agr% |
|---------|-----|------|
| x0.85 | 0.3170 | 97.5% |
| x1.00 | 0.3330 | 100.0% |
| x1.15 | 0.3435 | 97.4% |