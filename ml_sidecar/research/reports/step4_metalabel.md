# Step 4 — Meta-labeler
**Date:** 2026-07-20

## Configuration
- Strategy: Variant D (30min pure time), v1 models
- OOF: 2023-2026 (3,325 trades)
- Features: conf, hour, mins_open, dow, is_ce, consec, entry_premium
- Model: XGBoost binary, walk-forward by year

## Cutoff Evaluation
Base: 3,325 trades, net 276,176

| Cutoff | Trades | Retain% | Win% | Net PnL | PF |
|--------|--------|---------|------|---------|-----|
| 0.0 | 3325 | 100% | 45% | 276,176 | 1.19 |
| 0.4 | 2633 | 79% | 46% | 219,796 | 1.17 |
| 0.5 | 8 | 0% | 75% | 4,186 | 4.40 |
| 0.6 | 8 | 0% | 75% | 4,186 | 4.40 |