# Spectre ML Sidecar — Model Registry

Single source of truth for every ML model living in `ml_sidecar/`. Update this file whenever a model is added, retrained, or removed.

## Directory layout

```
ml_sidecar/
├── sidecar.py                          # FastAPI server, port 8240
├── requirements.txt
└── models/
    ├── nifty_rolling_model*.pkl        # → A. Rolling Master
    ├── nifty_direction_model_5m*.pkl   # → B. Direction (5m)
    ├── nifty_direction_model.pkl       # → C. OldDirection (1h)
    ├── nifty_cross_asset_model*.pkl    # → D. Cross-Asset
    ├── nifty_scalper_lstm*.keras       # → E. 3m Scalper LSTM
    └── overnight_nifty/                # → F. Overnight Nifty (v3, this doc's main subject)
```

## Models in production

| ID | Name | Type | Horizon | Endpoint | Trigger |
|---|---|---|---|---|---|
| A | Rolling Master | XGBoost | 5m rolling | `/predict` | on-demand |
| B | Direction (5m) | XGBoost | 5m | `/predict` | on-demand |
| C | OldDirection (1h) | XGBoost | 1h trend | `/predict`, `/morning-predict` | on-demand |
| D | Cross-Asset | XGBoost | 5m | `/predict` | on-demand |
| E | 3m Scalper LSTM | LSTM | 3m | `/predict-scalper` | on-demand |
| **F** | **Overnight Nifty (v3)** | **Stacked XGB+LGBM + Regression** | **next NSE day close** | **`/predict_nifty_overnight`** | **daily 03:30 IST cron** |

---

## F. Overnight Nifty (v3 stacked + regression)

**Purpose.** Predict the next NSE trading day's closing Nifty 50 level using only information available by ~03:30 IST: US session close from yesterday, European close, Asian overnight session, FX, commodities, bond yields, and lagged Nifty technicals. Output is generated every day with a confidence score; the user decides whether to act on each prediction.

### Sub-components

This is actually two models combined behind a single endpoint:

| Sub-model | File | Output | Walk-forward perf |
|---|---|---|---|
| Direction ensemble | `stacked_v3_xgb.pkl` + `stacked_v3_lgb.pkl` + `stacked_v3_meta.pkl` + `stacked_v3_calibrators.pkl` | `direction` (UP/DOWN/FLAT) + `direction_confidence` (0-1, calibrated) | 51% unfiltered → 75% @ confidence ≥0.55 → 79% @ confidence ≥0.60 |
| Close-price regression | `regression_v3_xgb.pkl` | `predicted_close` (₹) + `predicted_change_pct` + derived `magnitude_bucket` | 0.62% MAE on close (5y walk-forward) |

### Architecture details (direction ensemble)

```
                ┌── XGBoost (depth=4, n=500) ──┐
74 features ──→ │                              │ → 6 base probs ──→ Logistic Regression
                └── LightGBM (leaves=15, n=500)┘   (per fold,        (multinomial,
                                                    walk-forward)    class-balanced)
                                                                            │
                                                                            ▼
                                                              Per-class isotonic
                                                              calibration (3 calibrators)
                                                                            │
                                                                            ▼
                                                              calibrated direction probs
```

### Features (74 total)

**Lagged Nifty technicals (9):** 1d/5d/20d returns, RSI(14), high-low range %, 20d realised vol, distance from 20d/50d MA, volume z-score.

**Cross-asset overnight returns (33):** S&P 500, Nasdaq, VIX, US 10Y yield, DXY, USD/INR, Brent, Gold, Copper, Nikkei, Hang Seng, KOSPI, MOVE, FTSE, DAX — each as 1d/5d/20d returns.

**Levels & regime (4):** VIX level, VIX vs 20d MA, USD/INR level, US 10Y level.

**Calendar (7):** day-of-week (one-hot Mon-Fri), month, day-of-week numeric.

**Interaction / regime features (9, added in v3):**
- `us_asia_bull_agree` — S&P up AND ≥2 of {KOSPI, HSI, Nikkei} up
- `us_asia_bear_agree` — symmetric bearish version
- `asia_bull_count` — count of positive Asia indices (0–3)
- `vix_regime_low/mid/high` — one-hot for VIX regime (<13 / 13-20 / ≥20)
- `nifty_rv_vs_vix` — Nifty 20d annualised realised vol minus VIX (vol surprise indicator)
- `inr_nifty_divergence` — INR depreciation × Nifty return (catches unusual co-movement)
- `nifty_up_freq_20` — fraction of last 20 days that were positive

### Data inputs

All from `yfinance` daily bars. Source-of-truth file: `models/overnight_nifty/data/overnight_raw.parquet` (~10y, ~2500 trading days).

**Known gaps (deferred):**
- **GIFT Nifty** — yfinance has no usable ticker. Would lift accuracy noticeably.
- **FII/DII flows** — single highest-value missing feature. Free sources are Akamai-protected; needs ~1-2 days of robust scraper work or a paid feed.
- **India 10Y yield** — not on yfinance under standard tickers.

### Training pipeline

```
data_fetcher.py            # 10y daily OHLCV from yfinance → overnight_raw.parquet
feature_engineering.py     # builds 74 features + targets (logret, dir, mag)
train_stacked_v3.py        # walk-forward XGB+LGBM, fits meta + calibrators
train_regression_v3.py     # walk-forward XGB regression for close price
evaluate_holdout.py        # legacy v1 holdout eval (kept for reference)
```

Train/eval split:
- **Walk-forward CV:** 5 expanding folds, each tests on 1 calendar year (2021-2025). Each fold's training data ends *before* the fold start — no leakage.
- **Final fit:** train on all data ≤ 2026-03-31, holdout April 2026.

### Output schema (`/predict_nifty_overnight`)

```json
{
  "prediction_date":      "2026-04-25",
  "asof_session":         "2026-04-23",
  "target_date":          "2026-04-24",
  "prev_close":           24173.05,
  "predicted_close":      24179.39,
  "predicted_change_pct": 0.026,
  "direction":            "DOWN",
  "direction_confidence": 0.352,
  "direction_probs": {"DOWN": 0.352, "FLAT": 0.302, "UP": 0.345},
  "magnitude_bucket":     "TINY",
  "abs_change_pct":       0.026,
  "model_version":        "v3",
  "feature_freshness":    "2026-04-23"
}
```

`/predict_nifty_overnight/log?limit=N` returns the last N predictions including backfilled `actual_close`, `abs_error_pct`, `direction_correct`.

### Persistence

Every prediction is appended to `models/overnight_nifty/data/overnight_predictions.csv`. The 16:00 IST backfill job populates `actual_close` once NSE closes for the day.

### Schedulers (APScheduler, in-process)

| Time (IST) | Job | What it does |
|---|---|---|
| 03:30 | predict | Refetches yfinance (incremental), runs `predict_and_log()` |
| 16:00 | backfill | Refetches yfinance, fills `actual_close` for the day's prediction |

Disable with env var `SPECTRE_DISABLE_SCHEDULER=1`.

### Performance summary

See [`backtest/overnight_lstm_holdout/DECISION.md`](../backtest/overnight_lstm_holdout/DECISION.md) for the full evaluation. Headline numbers (5-year walk-forward 2021-2025):

| Confidence | Trades / 5y | Trades/year | Directional accuracy |
|---:|---:|---:|---:|
| 0.45 | 476 | 95 | 60% |
| 0.50 | 263 | 53 | 71% |
| 0.55 | 233 | 47 | **75%** |
| 0.60 | 187 | 37 | **79%** |
| 0.65 | 167 | 33 | 81% |

Close-price MAE: **0.62%** (5-year walk-forward), 0.67% on April 2026 holdout.

### Retraining cadence

Recommended: **monthly** retrain by re-running:
```bash
cd ml_sidecar/models/overnight_nifty
../../venv/bin/python data_fetcher.py
../../venv/bin/python train_stacked_v3.py
../../venv/bin/python train_regression_v3.py
```
Each run is < 5 minutes.

### Not in v3 / deferred

- LSTM direction model (`lstm_direction.keras`) — was tested in v2, decisively worse than XGB; kept on disk for reference but not loaded by the sidecar.
- Multi-task LSTM v1 (`overnight_lstm.keras`) — collapsed to all-DOWN, not used.
- FII/DII feature pipeline — see `fii_dii_fetcher.py` (stub) for next-iteration TODO.
- GIFT Nifty feature — needs paid feed.

---

## Models A–E (existing intraday/scalp models)

These predate the overnight model and are documented in [`SPECTRE_ARCHITECTURE.md`](../SPECTRE_ARCHITECTURE.md). The overnight model is independent of them — different inputs (yfinance daily bars vs live 1m/5m), different horizon (next-day close vs intraday), different consumer (advisory output vs live trade triggers).
