# Overnight Nifty — Stacked Ensemble v3 Report

**Trained at:** 2026-04-27T19:35:18.157038Z  
**Architecture:** XGBoost + LightGBM → Logistic meta → isotonic calibration  
**Features:** 90 (added 9 interaction/regime features in v3)

## Walk-forward base learners

| Fold | Test window | n | XGB acc | XGB dir-only | LGB acc | LGB dir-only |
|---|---|---:|---:|---:|---:|---:|
| 1 | 2021-01-01→2021-12-31 | 169 | 58.58% | 60.87% | 57.4% | 60.0% |
| 2 | 2022-01-01→2022-12-31 | 228 | 60.96% | 63.5% | 61.4% | 63.59% |
| 3 | 2023-01-01→2023-12-31 | 205 | 51.22% | 56.06% | 52.68% | 57.14% |
| 4 | 2024-01-01→2024-12-31 | 184 | 51.63% | 52.71% | 54.35% | 54.26% |
| 5 | 2025-01-01→2025-12-31 | 249 | 57.43% | 64.38% | 55.82% | 63.03% |

## Stacked OOF (walk-forward across all 5 folds)

- Uncalibrated stacked: 3-class **56.81%**, dir-only **61.41%** (n=736)
- Calibrated stacked:    3-class **58.16%**, dir-only **62.16%** (n=761)

## Conviction filter on calibrated stacked OOF

| Threshold | Trades / 5y | Trade frequency | Dir-only accuracy |
|---:|---:|---:|---:|
| 0.00 | 761 | 73.5% | 62.2% |
| 0.40 | 700 | 67.6% | 63.4% |
| 0.45 | 626 | 60.5% | 66.1% |
| 0.50 | 547 | 52.9% | 69.3% |
| 0.55 | 480 | 46.4% | 72.1% |
| 0.60 | 376 | 36.3% | 75.3% |
| 0.65 | 327 | 31.6% | 77.4% |
| 0.70 | 286 | 27.6% | 79.0% |

## April 2026 holdout

- 3-class: **87.5%**, dir-only: **85.7%** (n=14)

| date       | actual_dir   | pred_dir   |   p_down |   p_flat |   p_up |   p_top | correct   |
|:-----------|:-------------|:-----------|---------:|---------:|-------:|--------:|:----------|
| 2026-04-01 | UP           | UP         |    0.039 |    0.171 |  0.791 |   0.791 | True      |
| 2026-04-02 | FLAT         | DOWN       |    0.382 |    0.355 |  0.262 |   0.382 | False     |
| 2026-04-06 | UP           | UP         |    0.039 |    0.171 |  0.791 |   0.791 | True      |
| 2026-04-07 | UP           | UP         |    0.155 |    0.308 |  0.537 |   0.537 | True      |
| 2026-04-08 | UP           | UP         |    0.039 |    0.171 |  0.791 |   0.791 | True      |
| 2026-04-09 | DOWN         | DOWN       |    0.447 |    0.41  |  0.143 |   0.447 | True      |
| 2026-04-10 | UP           | UP         |    0.225 |    0.376 |  0.398 |   0.398 | True      |
| 2026-04-13 | DOWN         | UP         |    0.22  |    0.336 |  0.444 |   0.444 | False     |
| 2026-04-15 | UP           | UP         |    0.054 |    0.233 |  0.713 |   0.713 | True      |
| 2026-04-16 | FLAT         | FLAT       |    0.318 |    0.359 |  0.323 |   0.359 | True      |
| 2026-04-17 | UP           | UP         |    0.057 |    0.322 |  0.621 |   0.621 | True      |
| 2026-04-20 | FLAT         | FLAT       |    0.389 |    0.396 |  0.215 |   0.396 | True      |
| 2026-04-21 | UP           | UP         |    0.195 |    0.364 |  0.441 |   0.441 | True      |
| 2026-04-22 | DOWN         | DOWN       |    0.723 |    0.184 |  0.093 |   0.723 | True      |
| 2026-04-23 | DOWN         | DOWN       |    0.691 |    0.216 |  0.093 |   0.691 | True      |
| 2026-04-24 | DOWN         | DOWN       |    0.797 |    0.203 |  0     |   0.797 | True      |
