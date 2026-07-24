# Overnight — O4 Holdout Validation (extended)

**Holdout:** 2026-04-01 -> 2026-04-09 (6 trading days, DB-limited to Jun 29 2026)
**Model:** stacked-v3, trained < 2026-04-01
**OOF baseline (2021-25):** 64.0% dir acc, +0.31% mean open->close capture (from overnight_o3_o5.md)

## Accuracy

| Metric | Holdout | OOF | Delta |
|---|---|---|---|
| Dir-only accuracy | 100.0% (n=5) | 64.0% (n=698) | +36.0pp |
| UP accuracy | 100.0% (n=4) | 64.1% | - |
| DOWN accuracy | 100.0% (n=1) | 64.0% | - |

## Open->Close Capture (the tradeable metric — NOT the same as directional accuracy)

A day can be directionally "correct" (predicted close_T vs close_{T-1} sign matches)
while still being a LOSING open->close trade, if the move happens as a gap that partially
reverses intraday. This is the number that matters for the futures strategy in O3.

| Metric | Holdout | OOF baseline |
|---|---|---|
| Mean captured (gross) | +0.454% | +0.31% |
| Win rate | 80% | 69% |
| Mean net (after 0.05% cost) | +0.404% | +0.26% |

## Per-Month

| Month | N | Dir Acc | Mean Captured | Win% |
|---|---|---|---|---|
| 2026-04 | 5 | 100% | +0.454% | 80% |

## Per-Day

| Date | Pred | Actual | Correct | Conf | Intraday | Captured |
|------|------|--------|---------|------|----------|----------|
| 2026-04-01 | UP | UP | Y | 0.84 | -0.96% | -0.96% |
| 2026-04-06 | UP | UP | Y | 0.84 | +0.83% | +0.83% |
| 2026-04-07 | UP | UP | Y | 0.54 | +1.25% | +1.25% |
| 2026-04-08 | UP | UP | Y | 0.84 | +0.60% | +0.60% |
| 2026-04-09 | DOWN | DOWN | Y | 0.47 | -0.56% | +0.56% |

## Caveats

- **Still a limited window (5 directional days over ~3 months)** — better than the
  original 6-day cut, but nowhere near the statistical power of the 698-trade OOF period.
  Do not treat this as confirming or refuting the OOF edge on its own.
- **Selection optimism risk unresolved**: architecture/features/thresholds were iterated on
  2021-2025; this window is still recent and close to that development period.
- **Live VPS comparison**: Not found locally.
  A genuine live comparison (VPS predictions vs what actually happened, logged in real time
  with no possibility of hindsight/lookahead) is the strongest evidence available and is
  still missing — need the full `overnight_predictions.csv` from the VPS Downloads tab.
- **ROOT CAUSE of the tiny window**: `overnight_raw.parquet` (built 2026-05-03) has
  NaN gaps in foreign/sector columns starting 2026-04-06 (HSI/FTSE/DAX) and 04-09
  (nifty_fin/infra), so build_features `dropna()` truncates the holdout to Apr 1-9.
  This is NOT a real 3-month test — it is a stale-data artifact. To get a genuine
  Apr-Jun 2026 holdout, re-run `overnight_nifty/data_fetcher.py` to rebuild the raw
  parquet with complete coverage, THEN rerun this script.