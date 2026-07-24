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

## ⚠️ O1+O2 REVIEW (senior pass, 2026-07-24): O1 PASSES, O2 finding is decisive but incomplete + has a bug

Script `overnight/o1_o2_validate.py` was committed (bad6c0e) but **no report was
written and no output captured**; senior-run results below.

**O1 — Directional symmetry: PASSES (genuine, symmetric edge).**
- Says UP: 64.1% (n=415) · Says DOWN: 64.0% (n=283) — the DOWN side is just as
  accurate as UP, so this is NOT an up-drift follower (unlike intraday variant D).
- Actual-UP base rate among directional days = 42.6%; model = 64.0% → large real edge.
- Symmetric and monotonic at every conviction threshold (64% → 80% @ 0.65, UP and
  DOWN improving together). Reasonably stable per-year (54–71%). O1 is a clear pass.

**O2 — Gap decomposition: TRADEABLE via futures. (Corrected — the committed
script had two bugs that inverted its conclusion.)**

Script bugs found & fixed in review:
1. **Units**: returns printed ×100 too large.
2. **One-day alignment (fatal)**: the model's pred dated T targets the SAME-day
   move close_{T-1}→close_T (verified: `actual_dir` matches same-day sign 87.5%
   vs next-day 55%), but the script measured close_T→close_{T+1} — pure noise.
   Its "open entry captures ~nothing" claim was this bug, not reality.

**Timing (resolved via feature_engineering.py):** each row T uses Nifty through
T-1 close + overnight US/global data "known by ~03:30 IST on day T", and predicts
close_T vs close_{T-1}. So the prediction exists before the 09:15 open → the
feasible, no-look-ahead entry is **open_T → exit close_T** (an intraday cash-session
futures trade, no overnight gap risk).

**Corrected capture (open_T→close_T, signed by prediction), OOF 2021–25, n=698:**

| conf | n | open→close ret | win% | close→close (accuracy proxy) | dir acc |
|------|----|------|------|------|------|
| 0.00 | 698 | **+0.309%** | 69% | +0.595% | 64% |
| 0.55 | 429 | **+0.427%** | 75% | +0.803% | 73% |
| 0.60 | 385 | **+0.444%** | 75% | +0.860% | 75% |
| 0.65 | 294 | **+0.501%** | 78% | +0.959% | 80% |

Net of ~0.03% futures round-trip: **+0.28%/trade (conf 0) to +0.41%/trade
(conf≥0.6, 385 trades/5y)**. The gap (mean |0.43%|) adds more but isn't
capturable; the **intraday open→close portion alone is a strong, executable edge**
— the opposite of the buggy script's conclusion. Instrument MUST be futures;
options (1–3% spread) would eat a 0.3–0.5% move (Phase-3 lesson).

**O2 verdict: PASS (futures, open→close entry).** Remaining: rewrite the script
cleanly + `reports/overnight_o1_o2.md` with these corrected numbers.

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
