# Conviction-only filter analysis (XGBoost walk-forward)

This evaluates whether the XGBoost direction model has higher accuracy on a *subset* of days where it is confident or where Asia overnight cues agree with its prediction. If so, conviction-only trading can extract edge from a model that's mediocre on average.

Total walk-forward UP/DOWN predictions across 2021-2025: **1035**

## 1. Confidence threshold filter

Trade only when the model's top-class probability is ≥ threshold.

|   threshold |   trades |   trade_freq_pct |   directional_acc_pct |
|------------:|---------:|-----------------:|----------------------:|
|        0    |      785 |             75.8 |                  51.6 |
|        0.4  |      754 |             72.9 |                  52.9 |
|        0.45 |      687 |             66.4 |                  54.3 |
|        0.5  |      602 |             58.2 |                  56.1 |
|        0.55 |      516 |             49.9 |                  58.3 |
|        0.6  |      440 |             42.5 |                  60   |
|        0.65 |      363 |             35.1 |                  63.9 |
|        0.7  |      298 |             28.8 |                  67.8 |

## 2. Asia agreement filter

Trade only when at least K of {KOSPI, HSI, Nikkei} overnight returns share the same sign as the predicted direction.

|   min_asia_agree |   trades |   trade_freq_pct |   directional_acc_pct |
|-----------------:|---------:|-----------------:|----------------------:|
|                0 |      785 |             75.8 |                  51.6 |
|                1 |      752 |             72.7 |                  52.3 |
|                2 |      622 |             60.1 |                  53.9 |
|                3 |      330 |             31.9 |                  63.6 |

## 3. Combined filter

|   prob_threshold |   min_asia_agree |   trades |   trade_freq_pct |   directional_acc_pct |
|-----------------:|-----------------:|---------:|-----------------:|----------------------:|
|             0.45 |                1 |      665 |             64.3 |                  54.4 |
|             0.45 |                2 |      565 |             54.6 |                  56.1 |
|             0.5  |                1 |      586 |             56.6 |                  56.5 |
|             0.5  |                2 |      511 |             49.4 |                  57.9 |
|             0.55 |                1 |      508 |             49.1 |                  58.7 |
|             0.55 |                2 |      454 |             43.9 |                  59   |

## Notes

- Coin-flip baseline = 50% on directional preds.
- After typical Indian retail costs (brokerage + slippage on Nifty options ≈ 0.05-0.15% per trade), break-even directional accuracy is ~52-55%.
- A filter is useful if it raises directional accuracy above ~55% while keeping trade count ≥ ~30/year.
