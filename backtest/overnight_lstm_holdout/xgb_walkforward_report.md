# Overnight Nifty XGBoost — Direction-only baseline (v2)
**Trained at:** 2026-04-24T19:33:47.385152Z  
**Features:** 65 (after dropping Dow, adding HSI/KOSPI/Copper/MOVE/FTSE/DAX)  
**Train through:** 2026-03-31  |  **Holdout from:** 2026-04-01

## Walk-forward summary
- Average 3-class accuracy: **48.83%**  (random=33.3%, all-majority≈38%)
- Average directional-only accuracy (UP/DOWN preds, ignoring FLAT): **50.84%**  (coin-flip=50%)

| Fold | Train window | Test window | Test n | 3-class acc | Dir-only acc (n) | Predicted dist |
|---|---|---|---:|---:|---|---|
| 1 | 2016-06-09 → 2020-12-31 | 2021-01-01 → 2021-12-31 | 169 | 49.7% | 53.24% (n=139) | {'DOWN': 59, 'FLAT': 30, 'UP': 80} |
| 2 | 2016-06-09 → 2021-12-31 | 2022-01-01 → 2022-12-31 | 228 | 56.14% | 59.02% (n=205) | {'DOWN': 96, 'FLAT': 23, 'UP': 109} |
| 3 | 2016-06-09 → 2022-12-30 | 2023-01-01 → 2023-12-31 | 205 | 46.34% | 48.59% (n=142) | {'DOWN': 49, 'FLAT': 63, 'UP': 93} |
| 4 | 2016-06-09 → 2023-12-29 | 2024-01-01 → 2024-12-31 | 184 | 44.57% | 44.17% (n=120) | {'DOWN': 40, 'FLAT': 64, 'UP': 80} |
| 5 | 2016-06-09 → 2024-12-31 | 2025-01-01 → 2025-12-31 | 249 | 47.39% | 49.16% (n=179) | {'DOWN': 61, 'FLAT': 70, 'UP': 118} |

## Final-model holdout (April 2026)
- 3-class accuracy: **66.67%**
- Directional-only accuracy: **76.92%** on n=13
- Predicted distribution: {'DOWN': 3, 'FLAT': 2, 'UP': 10}

### Per-day predictions

| date       | actual_dir   | pred_dir   |   p_down |   p_flat |   p_up | correct   |
|:-----------|:-------------|:-----------|---------:|---------:|-------:|:----------|
| 2026-04-01 | UP           | UP         |    0.015 |    0.036 |  0.949 | True      |
| 2026-04-02 | FLAT         | DOWN       |    0.678 |    0.152 |  0.17  | False     |
| 2026-04-06 | UP           | UP         |    0.128 |    0.054 |  0.818 | True      |
| 2026-04-07 | UP           | UP         |    0.289 |    0.231 |  0.481 | True      |
| 2026-04-08 | UP           | UP         |    0.059 |    0.082 |  0.859 | True      |
| 2026-04-09 | DOWN         | FLAT       |    0.319 |    0.394 |  0.287 | False     |
| 2026-04-10 | UP           | UP         |    0.165 |    0.367 |  0.468 | True      |
| 2026-04-13 | DOWN         | DOWN       |    0.562 |    0.291 |  0.147 | True      |
| 2026-04-15 | UP           | UP         |    0.033 |    0.192 |  0.775 | True      |
| 2026-04-16 | FLAT         | UP         |    0.096 |    0.246 |  0.658 | False     |
| 2026-04-17 | UP           | UP         |    0.286 |    0.283 |  0.43  | True      |
| 2026-04-20 | FLAT         | UP         |    0.252 |    0.331 |  0.417 | False     |
| 2026-04-21 | UP           | UP         |    0.288 |    0.202 |  0.509 | True      |
| 2026-04-22 | DOWN         | FLAT       |    0.32  |    0.538 |  0.142 | False     |
| 2026-04-23 | DOWN         | DOWN       |    0.426 |    0.238 |  0.335 | True      |

### Top features by importance

| Feature | Importance |
|---|---:|
| kospi_ret_1 | 0.0428 |
| hsi_ret_1 | 0.0309 |
| dax_ret_1 | 0.0271 |
| nikkei_ret_1 | 0.0267 |
| vix_level | 0.0224 |
| ftse_ret_1 | 0.0208 |
| dow_0 | 0.0179 |
| dax_ret_5 | 0.0178 |
| nifty_ret_5 | 0.0175 |
| sp500_ret_5 | 0.0165 |
| copper_ret_1 | 0.0154 |
| usdinr_level | 0.0153 |
| nifty_vol_20 | 0.0152 |
| sp500_ret_20 | 0.0152 |
| nifty_range_pct | 0.0150 |
