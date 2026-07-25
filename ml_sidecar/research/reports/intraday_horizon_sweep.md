# Intraday Horizon Sweep — Correcting the "dead end" verdict

**Date:** 2026-07-26 · **Data:** 2020–2026 (488,962 bars), price/technical features only (clock excluded)

## Why this was run
The Step-3 conclusion "intraday directional signal is a null (AUC 0.52)" tested only
the **30-minute** horizon. This sweep asks whether a *different cadence* carries signal.
It does. The earlier verdict was too broad.

## Q1 — Directional AUC by horizon × move-threshold (move-only 2-class, time split)

Signal concentrates at SHORT horizons on SIGNIFICANT moves:

| | 5m | 10m | 15m | 20m | 30m | 45m | 60m |
|---|---|---|---|---|---|---|---|
| thr 0.10% | 0.547 | 0.530 | 0.527 | 0.521 | 0.522 | 0.529 | 0.536 |
| **thr 0.15%** | **0.561** | **0.557** | 0.546 | 0.537 | 0.535 | 0.538 | 0.537 |
| thr 0.20% | 0.546 | 0.551 | 0.542 | 0.532 | 0.530 | 0.544 | 0.542 |

## Q2 — Walk-forward stability (5m @ 0.15%, test by year)
2022: 0.575 · 2023: 0.529 · 2024: 0.593 · 2025: 0.570 · 2026: 0.550 — **positive every year.**
(10m @ 0.15% similar: 0.548 / 0.540 / 0.573 / 0.546 / 0.583.) Not a regime fluke.

## Q3 — Confidence filtering (5m @ 0.15%, walk-forward OOF, n=12,208)
Accuracy rises monotonically with model confidence — confidence is MEANINGFUL
(the old live system had *inverted* confidence):

| Filter | n | Dir acc | ~gross option pts/trade (0.5Δ) |
|---|---|---|---|
| all | 12,208 | 55.5% | +2.9 |
| top 25% | 3,052 | 61.4% | +5.9 |
| **top 10%** | 1,221 | **64.9%** | **+8.0** |

Round-trip ATM-weekly option cost ~2–4 pts → top-decile gross clears it with margin.

## Verdict
- **Dead**: predicting 30-min direction from technical indicators (0.52).
- **ALIVE (new lead)**: 5–10 min horizon + significant-move + confidence filter →
  ~65% directional at the top decile, walk-forward stable, ~2 signals/day.
- **Unproven before it's tradeable**: (1) real option-premium backtest with 1–3%
  spreads + the losing volatile days; (2) a live-feasible "is a move coming?" gate
  (two-stage P(move)×P(dir|move)) — training was move-only; (3) add OI/PCR features
  (already logged live) to push top-decile from 65% toward 70%+.
