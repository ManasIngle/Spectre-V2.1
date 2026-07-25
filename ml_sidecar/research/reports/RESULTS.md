# Phase 3 — Consolidated Results (Intraday Investigation)

**Closed:** 2026-07-23 · **Verdict: intraday signal has no tradeable edge. Pivot to overnight.**

## What was built & run
Offline replay harness (DB 2020–2026, faithful port of the live pipeline),
6.5-year event-driven geometry backtest with Black-Scholes premiums + costs,
a walk-forward calibrated v2 retrain, and a decisive set of diagnostics.

## Headline findings (each verified independently in review)

1. **Replay (Step 1/1b)** — harness faithful; live-vs-replay agreement 60.9% is
   genuine vendor skew, not a bug. Root cause (measured): Yahoo 1m bar ranges
   ~15% tighter than NSE, and the v1 models lean ~40% on `feat_hour` — so ATR/
   hour branches flip across vendors. The earlier "volume feature" story was
   false (volume = 0 in training CSV, DB, and Yahoo alike).

2. **Geometry (Step 2/2b)** — over 42k+ trades 2020–26, every spot-target/SL
   variant loses; the live 2:1 target:SL geometry (variant A) reproduces the
   78-day live loss signature. Time-exit variant D looked best (+₹475k, PF 1.14).

3. **Retrain (Step 3/3b)** — the directional thesis is a **NULL**:
   - Clock-free model collapses to a SIDEWAYS predictor (100% of conf≥60
     predictions are NO-TRADE).
   - **2-class UP-vs-DOWN AUC = 0.52** (move-only, 237k rows, time split) — the
     40 technical features carry no directional edge at 30-min horizon. v1's
     apparent skill was the time-of-day base rate + a calm/volatile detector.

4. **Variant D validation (decisive)** — D's +₹475k is **long-gamma, not skill**
   (net PnL corr 0.93 with spot move; profitable even in negative-drift years).
   Repricing its 8,927 trades against realistic bid-ask: **break-even at 0.60%
   full spread**; real weekly spreads are 1–3%. At 1% → −₹203k, at 2% → −₹709k.
   The edge was entirely the 5bps cost artifact.

## UPDATE 2026-07-26 — the "dead end" was too broad (see intraday_horizon_sweep.md)
The null below is specific to the **30-minute** horizon. A horizon sweep found a
real, walk-forward-stable directional edge at **5–10 min on significant (0.15%+)
moves**: top-decile confidence hits ~65% dir accuracy, ~2 signals/day, positive
every year 2022–26. This is a live lead, pending (1) a realistically-costed option
backtest, (2) a two-stage "is a move coming?" gate, (3) OI/PCR features. Intraday
is NOT closed — the specific 30-min-technical-directional bet is.

## Bottom line
- Intraday **directional** prediction **at 30-min from technicals**: dead. But
  short-horizon (5–10 min) significant-move signals are a live research track.
- Intraday **long-gamma** (variant D): dies on real option spreads. Not tradeable.
- Step 4 meta-labeler: moot on a 0.52-AUC base. Shelved.
- **Value delivered**: 5 steps of honest work prevented deploying real money on a
  non-edge, and produced a trustworthy backtester + the measurement infrastructure.

## Production proposal (NOT implemented — for review)
- Do **not** promote any v2 intraday artifact. Leave live intraday as paper-only
  research logging (keeps the signal dataset flowing).
- If intraday is ever revisited: change the *problem* (volatility/regime, not
  direction) and validate the premium/cost model against real option quotes FIRST.
- Redirect ML effort to the **overnight** model — see `OVERNIGHT_VALIDATION_PLAN.md`.
- Carry-forward caveat for any options backtest: flat-VIX BS with thin costs
  overstates long-gamma P&L; model 1–3% spreads + event IV-crush.
