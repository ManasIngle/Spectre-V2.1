# Overnight Model — O3 (Money Test) + O5 (Calibration Honesty)

**OOF period:** 2021–2025 (698 directional trades) · **Instrument:** Nifty futures
**Strategy:** on each directional prediction (dated T, available ~03:30 IST), enter
futures at **open_T**, exit at **close_T** — intraday, no overnight gap risk.
**Costs:** 0.05% round-trip on notional (STT + txn/GST/stamp + brokerage + open-fill
slippage); sensitivity 0.03–0.08% shown.

## O5 — how calibration optimism is handled
The OOF confidences were isotonic-calibrated *in-sample* (~5pp optimistic, per the
team's own DECISION.md). So:
- **Primary book = conf=0 (ALL 698 directional trades)** — needs no calibrator,
  immune to that critique.
- Conviction-filtered books shown as upside, each also with a **−5pp accuracy
  haircut** (correct trades flipped to losses) as a conservative floor.

## O3 — Results (net of 0.05% cost, % of notional per 1-lot trade)

| Book | n | net/trade | 5y total | win% | PF | maxDD | Sharpe* |
|---|---|---|---|---|---|---|---|
| **conf=0 (primary, calibration-free)** | 698 | **+0.259%** | +180% | 67% | 2.67 | −3.5% | 4.2 |
| conf≥0.55 raw | 429 | +0.377% | +162% | 73% | 4.34 | −2.1% | 4.7 |
| conf≥0.55 −5pp haircut | 429 | +0.317% | +136% | 69% | 3.19 | −3.0% | 3.4 |
| conf≥0.60 −5pp haircut | 385 | +0.343% | +132% | 69% | 3.63 | −2.5% | 3.6 |

*Sharpe annualized at actual ~140 trades/yr.
Per-year net is **positive every year 2021–2025** in all books (e.g. primary:
2021 +45%, 2022 +42%, 2023 +22%, 2024 +37%, 2025 +35%).

## Robustness checks (all pass)
- **Not outlier-driven**: median trade +0.29% (≈ mean 0.31%); top-5 days = only 8% of total.
- **Symmetric**: UP and DOWN both ~64% accurate (O1).
- **Cost-insensitive**: still +0.23%/trade even at 0.08% round-trip.
- **Shallow drawdown**: −3.5% max on notional over 5y.

## ⚠️ The honest caveat (why this is NOT yet a green light)
Sharpe ~4 and a 67% intraday win rate are **implausibly high for live trading** and
almost certainly contain **selection optimism**: although predictions are
walk-forward OOF, the model *architecture, 127 features, and conviction thresholds
were all chosen by iterating on this exact 2021–2025 period* (v1→v2→v3). Walk-forward
does not remove that. Expect the true forward Sharpe to be materially lower. This is
the same "too good to be true" smell that flagged the earlier 94–98% leakage bug —
treat it with the same suspicion.

## Verdict & next step
O3 **passes** as a research result: a genuine, symmetric, cost-robust, every-year-
positive edge, tradeable via **futures** (never options — a 1–3% spread eats a
0.3% move). But the magnitude is optimistic and **must not be sized with real money
until O4**: the true out-of-sample test on data the model development never saw —
**April–June 2026 holdout + the live overnight predictions the VPS has logged since
deploy**. If forward accuracy holds near ~60% with positive open→close capture,
this becomes a real, deployable strategy. If it collapses toward 50%, it was
selection optimism. O4 is the decision gate.
