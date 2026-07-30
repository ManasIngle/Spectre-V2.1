# Overnight — O4 Holdout Validation (extended)

**Holdout:** 2026-04-01 -> 2026-07-30 (82 trading days, DB-limited to Jun 29 2026)
**Model:** stacked-v3, trained < 2026-04-01
**OOF baseline (2021-25):** 64.0% dir acc, +0.31% mean open->close capture (from overnight_o3_o5.md)

## Accuracy

| Metric | Holdout | OOF | Delta |
|---|---|---|---|
| Dir-only accuracy | 60.3% (n=68) | 64.0% (n=698) | -3.7pp |
| UP accuracy | 57.9% (n=38) | 64.1% | - |
| DOWN accuracy | 63.3% (n=30) | 64.0% | - |

## Open->Close Capture (the tradeable metric — NOT the same as directional accuracy)

A day can be directionally "correct" (predicted close_T vs close_{T-1} sign matches)
while still being a LOSING open->close trade, if the move happens as a gap that partially
reverses intraday. This is the number that matters for the futures strategy in O3.

| Metric | Holdout | OOF baseline |
|---|---|---|
| Mean captured (gross) | +0.186% | +0.31% |
| Win rate | 65% | 69% |
| Mean net (after 0.05% cost) | +0.136% | +0.26% |

## Per-Month

| Month | N | Dir Acc | Mean Captured | Win% |
|---|---|---|---|---|
| 2026-04 | 16 | 81% | +0.365% | 75% |
| 2026-05 | 16 | 38% | +0.267% | 75% |
| 2026-06 | 19 | 53% | -0.028% | 47% |
| 2026-07 | 17 | 71% | +0.182% | 65% |

## Per-Day

| Date | Pred | Actual | Correct | Conf | Intraday | Captured |
|------|------|--------|---------|------|----------|----------|
| 2026-04-01 | UP | UP | Y | 0.84 | -0.96% | -0.96% |
| 2026-04-06 | UP | UP | Y | 0.84 | +0.83% | +0.83% |
| 2026-04-07 | UP | UP | Y | 0.54 | +1.25% | +1.25% |
| 2026-04-08 | UP | UP | Y | 0.84 | +0.60% | +0.60% |
| 2026-04-09 | DOWN | DOWN | Y | 0.47 | -0.56% | +0.56% |
| 2026-04-13 | UP | DOWN | N | 0.51 | +1.07% | +1.07% |
| 2026-04-15 | UP | UP | Y | 0.72 | +0.28% | +0.28% |
| 2026-04-17 | UP | UP | Y | 0.62 | +0.78% | +0.78% |
| 2026-04-21 | UP | UP | Y | 0.54 | +0.83% | +0.83% |
| 2026-04-22 | DOWN | DOWN | Y | 0.61 | -0.38% | +0.38% |
| 2026-04-23 | DOWN | DOWN | Y | 0.66 | -0.12% | +0.12% |
| 2026-04-24 | DOWN | DOWN | Y | 0.77 | -0.84% | +0.84% |
| 2026-04-27 | DOWN | UP | N | 0.60 | +0.61% | -0.61% |
| 2026-04-28 | DOWN | DOWN | Y | 0.66 | -0.23% | +0.23% |
| 2026-04-29 | DOWN | UP | N | 0.59 | +0.34% | -0.34% |
| 2026-04-30 | DOWN | DOWN | Y | 0.52 | +0.00% | -0.00% |
| 2026-05-04 | DOWN | UP | N | 0.66 | +0.23% | -0.23% |
| 2026-05-06 | UP | UP | Y | 0.84 | +0.66% | +0.66% |
| 2026-05-07 | UP | FLAT | N | 0.72 | -0.29% | -0.29% |
| 2026-05-08 | DOWN | DOWN | Y | 0.60 | -0.24% | +0.24% |
| 2026-05-11 | DOWN | DOWN | Y | 0.53 | -0.64% | +0.64% |
| 2026-05-12 | DOWN | DOWN | Y | 0.85 | -1.45% | +1.45% |
| 2026-05-13 | UP | FLAT | N | 0.38 | +0.21% | +0.21% |
| 2026-05-14 | UP | UP | Y | 0.75 | +0.68% | +0.68% |
| 2026-05-15 | DOWN | FLAT | N | 0.66 | -0.37% | +0.37% |
| 2026-05-18 | UP | FLAT | N | 0.62 | +0.71% | +0.71% |
| 2026-05-19 | DOWN | FLAT | N | 0.59 | -0.24% | +0.24% |
| 2026-05-20 | UP | FLAT | N | 0.51 | +0.86% | +0.86% |
| 2026-05-22 | UP | FLAT | N | 0.75 | +0.20% | +0.20% |
| 2026-05-25 | UP | UP | Y | 0.55 | +0.38% | +0.38% |
| 2026-05-26 | UP | DOWN | N | 0.51 | -0.38% | -0.38% |
| 2026-05-29 | UP | DOWN | N | 0.61 | -1.48% | -1.48% |
| 2026-06-01 | UP | DOWN | N | 0.75 | -1.15% | -1.15% |
| 2026-06-02 | DOWN | UP | N | 0.80 | +1.10% | -1.10% |
| 2026-06-03 | DOWN | DOWN | Y | 0.52 | -0.04% | +0.04% |
| 2026-06-04 | DOWN | FLAT | N | 0.40 | +0.58% | -0.58% |
| 2026-06-05 | DOWN | FLAT | N | 0.75 | -0.48% | +0.48% |
| 2026-06-08 | DOWN | DOWN | Y | 0.85 | +0.18% | -0.18% |
| 2026-06-09 | UP | UP | Y | 0.55 | -0.07% | -0.07% |
| 2026-06-10 | DOWN | FLAT | N | 0.85 | -0.08% | +0.08% |
| 2026-06-11 | UP | FLAT | N | 0.46 | +0.25% | +0.25% |
| 2026-06-12 | UP | UP | Y | 0.91 | +0.90% | +0.90% |
| 2026-06-15 | UP | UP | Y | 0.75 | -0.55% | -0.55% |
| 2026-06-16 | UP | UP | Y | 0.75 | +0.27% | +0.27% |
| 2026-06-18 | DOWN | UP | N | 0.47 | +0.39% | -0.39% |
| 2026-06-22 | UP | UP | Y | 0.61 | -0.02% | -0.02% |
| 2026-06-23 | DOWN | DOWN | Y | 0.78 | -1.03% | +1.03% |
| 2026-06-24 | UP | UP | Y | 0.55 | +0.95% | +0.95% |
| 2026-06-25 | UP | FLAT | N | 0.55 | -0.29% | -0.29% |
| 2026-06-29 | DOWN | DOWN | Y | 0.82 | -0.48% | +0.48% |
| 2026-06-30 | UP | DOWN | N | 0.38 | -0.69% | -0.69% |
| 2026-07-01 | DOWN | UP | N | 0.59 | +0.45% | -0.45% |
| 2026-07-02 | UP | UP | Y | 0.55 | +0.47% | +0.47% |
| 2026-07-03 | UP | UP | Y | 0.83 | -0.43% | -0.43% |
| 2026-07-06 | UP | UP | Y | 0.75 | +0.51% | +0.51% |
| 2026-07-08 | DOWN | DOWN | Y | 0.85 | -1.56% | +1.56% |
| 2026-07-09 | UP | UP | Y | 0.75 | +0.14% | +0.14% |
| 2026-07-10 | UP | UP | Y | 0.62 | +0.34% | +0.34% |
| 2026-07-13 | UP | FLAT | N | 0.38 | +0.71% | +0.71% |
| 2026-07-14 | DOWN | DOWN | Y | 0.61 | -0.07% | +0.07% |
| 2026-07-15 | UP | FLAT | N | 0.67 | -0.03% | -0.03% |
| 2026-07-16 | UP | FLAT | N | 0.55 | -0.29% | -0.29% |
| 2026-07-20 | DOWN | DOWN | Y | 0.78 | +0.20% | -0.20% |
| 2026-07-22 | DOWN | DOWN | Y | 0.82 | -0.64% | +0.64% |
| 2026-07-23 | DOWN | DOWN | Y | 0.47 | -0.15% | +0.15% |
| 2026-07-24 | DOWN | DOWN | Y | 0.47 | +0.43% | -0.43% |
| 2026-07-27 | UP | UP | Y | 0.83 | +0.28% | +0.28% |
| 2026-07-28 | UP | FLAT | N | 0.48 | +0.06% | +0.06% |

## Caveats

- **Still a limited window (68 directional days over ~3 months)** — better than the
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
---

## Significance & Conviction (senior analysis, 2026-07-27)

Data refreshed through 2026-07-30 (was stale at Apr 30). A `dropna()` truncation
bug capped the earlier run at 6 days — fixed by forward-filling the domestic
sector closes separately (ffill carries only PAST values forward, so it cannot
leak; the b578185 `.shift(1)` leakage fix is untouched). Holdout is now the full
**82 days / 68 directional**.

| Conviction | n | Dir acc | Net/trade | Total (window) | Win% |
|---|---|---|---|---|---|
| all | 68 | 60.3% | +0.136% | +9.27% | 63% |
| ≥0.50 | 58 | 65.5% | +0.171% | +9.92% | 64% |
| ≥0.60 | 41 | 70.7% | +0.142% | +5.84% | 68% |
| ≥0.65 | 32 | 71.9% | +0.184% | +5.89% | 69% |

**Statistical significance:** 41/68 = 60.3%, binomial p **= 0.057** vs a 50% coin
flip → **NOT significant at p<0.05** (it just misses). n=68 cannot prove a ~60% edge.

**Per-month:** Apr 81% · May **38%** · Jun 53% · Jul 71% — severe regime variance,
and May was *below* coin-flip. This is the single biggest risk in the result.

### Verdict — PASSES the stated gate, but is NOT yet proven
- The edge **survived** forward testing: 60.3% vs the 64.0% OOF baseline (−3.7pp).
  It did NOT collapse toward 50%, which was the failure case O3 warned about.
- **Conviction filtering holds up out-of-sample** (60.3 → 70.7 → 71.9% as the
  threshold rises). This is the strongest positive: it independently answers the
  O5 circular-calibration concern — on data the calibrator never saw, higher
  confidence really does mean higher accuracy.
- **Returns are ~half the backtest**: +0.136% net/trade vs +0.26% in O3. The
  selection optimism flagged in O3 is now quantified at roughly a 50% haircut.
- **Not statistically significant, and one sub-coin-flip month.** n must roughly
  double before a ~60% edge is provable.

**Recommendation: advisory / paper mode — do NOT size real money on this yet.**
Keep logging live predictions; re-run this test once the forward sample reaches
~150 directional days. If accuracy holds ≥60% (and ≥68% at conf≥0.60) with
significance, it becomes deployable on **futures** at the conviction threshold.
