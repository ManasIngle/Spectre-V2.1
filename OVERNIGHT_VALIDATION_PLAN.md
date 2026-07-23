# Overnight Model — Tradeability Validation Plan (Phase 4)

> **Why this exists**: Phase 3 proved the intraday signal was a null and that the
> ONE positive backtest died on realistic costs. The overnight model is
> different — it has genuine signal — but the SAME tradeability questions that
> sank intraday have never been asked of it. This plan asks them before any real
> money. Execution model: step-by-step, local commits `research(overnight-N):`,
> NO push, senior review at each checkpoint.

## What we know (from existing artifacts)
Stacked v3 (XGB+LGBM→LogReg→isotonic, 127 features incl. global macro, ADRs,
sector breadth). Walk-forward 2021–2025, 1035 UP/DOWN preds. Calibrated
dir-only accuracy: 52.8% @ conf 0 → 74.7% @ 0.55 → 80.3% @ 0.65 (~47 trades/yr
at 0.55). This is REAL signal (well above the ~53% up base-rate) and the leakage
bug that once faked 94–98% was fixed in commit b578185.

## What is NOT yet known (the tradeability gaps — the whole point of Phase 4)

### O1 — Is the edge real and symmetric, or a bull-market/base-rate artifact?
The intraday trap was "always-UP in an up-market." Test on stacked-v3 walk-forward
OOF (regenerate row-level OOF preds if not saved):
- Dir accuracy **split by predicted UP vs predicted DOWN**, per year. If DOWN
  predictions are at/below chance, the "edge" is just an up-drift follower.
- Baseline: always-UP, and always-follow-the-overnight-gap-sign. The model must
  beat both at matched trade counts.
- **Acceptance**: DOWN-side accuracy meaningfully > 50% AND model beats both
  baselines. If it fails, the overnight edge is also mostly beta — say so.

### O2 — The gap problem (THE decisive tradeability test)
The model predicts **next_close vs today_close**. Most of that move can happen at
the OPEN (overnight gap) which you cannot capture if you enter at the open.
Decompose the predicted move into:
- captured-at-open entry: `sign(pred) · (next_close − next_open)`
- today-close entry (futures/CFD): `sign(pred) · (next_close − today_close)`
Report accuracy AND mean captured return for each entry timing, per conviction
bucket. **This determines whether there is anything to trade and via which entry.**

### O3 — Realistic instrument backtest with real costs
Two candidate instruments, both costed honestly:
- **Nifty futures / next-month**: cost ~0.02–0.05% round-trip + overnight margin;
  gap risk borne. Cleanest expression of a directional overnight view.
- **Options (ATM next-day)**: apply the Phase-3 lesson — 1–3% bid-ask + overnight
  theta + event IV-crush. Likely worse; include to quantify.
Produce per-year net expectancy, PF, max DD, equity curve at conf {0.5, 0.55,
0.6, 0.65}. **Acceptance**: positive net expectancy after costs on futures at a
conviction threshold with ≥30 trades/yr, stable across years.

### O4 — Honest out-of-sample extension
Current holdout is n=20 (too small); the saved `predicted_vs_actual.csv` is the
OLD v1 LSTM (26.7%), not v3 — do not cite it. Extend true OOS: retrain ≤ 2026-03-31,
predict Apr–Jun 2026 (DB covers Indian data to Jun 29; macro via the overnight
data_fetcher). Then compare against the **live** overnight predictions the VPS has
been logging since deploy (if retrievable) — real forward test.

### O5 — Calibration honesty
DECISION.md already flags: calibrator fit on the same OOF used to score conviction
(~5pp optimistic). Redo with nested/causal calibration (calibrate fold k on folds
< k), rebuild the conviction table, and treat those as the real numbers.

## Sequencing
O1 → O2 first (cheap, decisive; if both fail, overnight is also mostly beta and we
stop before building infra). Then O5 (fixes the numbers), O3 (the money test),
O4 (forward validation). Only after O3 passes on futures do we discuss wiring
`/predict_nifty_overnight` into production / advisory mode.

## Data/code notes
- Overnight pipeline is self-contained in `ml_sidecar/models/overnight_nifty/`
  (data_fetcher.py = yfinance macro + local/DB Indian data; train_stacked_v3.py;
  predict_overnight.py). Reuse it; write validation scripts under
  `ml_sidecar/research/overnight/`. Do NOT modify production overnight files.
- Lot size 65; same cost-realism discipline as Phase 3.
- Every claim states its exact date range and trade count.
