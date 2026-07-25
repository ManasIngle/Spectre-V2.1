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

## Money test (2026-07-26) — the 65% was misleading; DIRECTION is not tradeable

Followed the lead to its decisive test (option + futures P&L, walk-forward OOF,
model applied to ALL bars = no look-ahead). Three findings, airtight:

1. **Long-option P&L is negative at every filter/spread** (top-2% signals: −0.5 to
   −2.2 pts/trade at 1–3% spread). You pay the spread on every trade; real moves are rare.
2. **Futures P&L ≈ 0 gross, negative net.** Applying direction to all bars, mean
   signed 5-min return is +0.003% (≈0.7 idx pts) — below even 0.015% futures cost.
   The 65% "accuracy" was conditional on a move happening; those are ~3% of bars, so
   the edge is diluted to ~nothing across all the bars you'd actually trade.
3. **Two-stage (move-gate × direction) also fails — and reveals why.** Move-TIMING
   IS strongly predictable (**AUC 0.82**; top-1% move-prob bars move 10× base rate).
   BUT on exactly those high-move bars, **direction collapses to 52–55%** (coin flip).
   You can predict WHEN a move comes, not WHICH WAY — especially when it matters.
   Every two-stage config is net-negative (−1 to −3 pts/trade).

### Final intraday verdict
- **Directional intraday: definitively dead** — tested 3 ways (30-min 0.52; 5-min
  all-bars ~0; two-stage 52–55% on movers). Direction is unpredictable at tradeable
  horizons, and *least* predictable on the volatile bars where it would pay.
- **The ONE strong intraday signal is move-TIMING (0.82 AUC), a VOLATILITY signal,
  not a directional one.** But neither expression is cost-viable (below).

## FINAL CLOSURE (2026-07-26) — every avenue tested, intraday is exhausted

| Avenue | Test | Result |
|---|---|---|
| Direction, 30-min, technicals | AUC | 0.52 — noise |
| Direction, 5-min, technicals | AUC / futures P&L | 0.56 but ~0 net; 52-55% on movers |
| Direction, BankNifty lead | AUC (DB, 1-min) | **0.52 — no lead-lag edge** |
| Long vol (buy straddle on predicted move) | — | dies on 2× spread (variant-D lesson) |
| **Short vol (sell straddle in calm)** | BS P&L | **gross ~0 (intraday theta tiny), −1.6 to −6.4 net after spread, ugly tails** |

**Structural reason it's all dead:** (1) direction is not in the available data at
any tradeable intraday horizon; (2) the real signal — move-timing — is volatility,
and every volatility expression pays the option bid-ask (1-3%/leg, ×2 for straddles)
which dwarfs the tiny intraday theta/gamma. Retail option spreads are the wall.

**What could change it (NOT available now):** true order-flow/microstructure or
live OI/PCR feature streams — neither in this DB. Until then, intraday is closed.
The project's real, validated edge is the OVERNIGHT model (futures, O1-O3 passed).
