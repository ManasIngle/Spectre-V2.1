# Overnight Nifty — Stacked Ensemble v3 Report

**Trained at:** 2026-04-25T07:32:22.515883Z  
**Architecture:** XGBoost + LightGBM → Logistic meta → isotonic calibration  
**Features:** 74 (added 9 interaction/regime features in v3)

## Walk-forward base learners

| Fold | Test window | n | XGB acc | XGB dir-only | LGB acc | LGB dir-only |
|---|---|---:|---:|---:|---:|---:|
| 1 | 2021-01-01→2021-12-31 | 169 | 50.3% | 52.45% | 49.7% | 51.75% |
| 2 | 2022-01-01→2022-12-31 | 228 | 56.14% | 59.9% | 56.58% | 59.9% |
| 3 | 2023-01-01→2023-12-31 | 205 | 46.83% | 49.64% | 46.34% | 50.0% |
| 4 | 2024-01-01→2024-12-31 | 184 | 44.57% | 45.83% | 47.83% | 50.0% |
| 5 | 2025-01-01→2025-12-31 | 249 | 48.19% | 50.0% | 47.39% | 48.88% |

## Stacked OOF (walk-forward across all 5 folds)

- Uncalibrated stacked: 3-class **49.57%**, dir-only **53.16%** (n=743)
- Calibrated stacked:    3-class **50.24%**, dir-only **52.83%** (n=778)

## Conviction filter on calibrated stacked OOF

| Confidence | Trades / 5y | Trade frequency | Dir-only accuracy |
|---:|---:|---:|---:|
| 0.00 | 778 | 75.2% | 52.8% |
| 0.40 | 701 | 67.7% | 54.4% |
| 0.45 | 476 | 46.0% | 60.1% |
| 0.50 | 263 | 25.4% | 70.7% |
| 0.55 | 233 | 22.5% | 74.7% |
| 0.60 | 187 | 18.1% | 78.6% |
| 0.65 | 167 | 16.1% | 80.8% |
| 0.70 | 143 | 13.8% | 81.1% |

## April 2026 holdout

- 3-class: **73.3%**, dir-only: **78.6%** (n=14)

| date       | actual_dir   | pred_dir   |   p_down |   p_flat |   p_up |   p_top | correct   |
|:-----------|:-------------|:-----------|---------:|---------:|-------:|--------:|:----------|
| 2026-04-01 | UP           | UP         |    0     |    0     |  1     |   1     | True      |
| 2026-04-02 | FLAT         | DOWN       |    0.447 |    0.338 |  0.215 |   0.447 | False     |
| 2026-04-06 | UP           | UP         |    0.232 |    0.272 |  0.496 |   0.496 | True      |
| 2026-04-07 | UP           | UP         |    0.24  |    0.356 |  0.404 |   0.404 | True      |
| 2026-04-08 | UP           | UP         |    0.147 |    0.118 |  0.735 |   0.735 | True      |
| 2026-04-09 | DOWN         | FLAT       |    0.368 |    0.369 |  0.263 |   0.369 | False     |
| 2026-04-10 | UP           | UP         |    0.239 |    0.308 |  0.453 |   0.453 | True      |
| 2026-04-13 | DOWN         | DOWN       |    0.447 |    0.338 |  0.215 |   0.447 | True      |
| 2026-04-15 | UP           | UP         |    0.137 |    0.25  |  0.612 |   0.612 | True      |
| 2026-04-16 | FLAT         | UP         |    0.218 |    0.316 |  0.466 |   0.466 | False     |
| 2026-04-17 | UP           | UP         |    0.261 |    0.335 |  0.404 |   0.404 | True      |
| 2026-04-20 | FLAT         | UP         |    0.252 |    0.324 |  0.424 |   0.424 | False     |
| 2026-04-21 | UP           | UP         |    0.239 |    0.308 |  0.453 |   0.453 | True      |
| 2026-04-22 | DOWN         | DOWN       |    0.41  |    0.393 |  0.197 |   0.41  | True      |
| 2026-04-23 | DOWN         | DOWN       |    0.352 |    0.302 |  0.345 |   0.352 | True      |
