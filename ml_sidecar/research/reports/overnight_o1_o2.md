# Overnight Model — O1 & O2 Validation

**OOF period:** 2021-01-01 to 2025-12-31 | **Predictions:** 1035 (698 directional)
**Model:** stacked-v3 (XGB+LGBM->LogReg->isotonic, 127 features)
**Timing:** pred dated T uses data through T-1 close + overnight US/global, predicts close_T vs close_{T-1}
**Feasible entry:** open_T, exit close_T (intraday, no overnight gap risk)

## O1 — Directional Symmetry

| Signal | N | Accuracy |
|---|---|---|
| UP | 415 | 64.1% |
| DOWN | 283 | 64.0% |
| Overall | 698 | 64.0% |
| Always-UP baseline | 698 | 42.6% |

**O1 verdict: PASS.** DOWN accuracy 64% — symmetric with UP. Not an up-market follower.

### Per-Year

| Year | N | UP N | UP Acc | DOWN N | DOWN Acc |
|------|---|-------|--------|--------|---------|
| 2021 | 123 | 72 | 67% | 51 | 61% |
| 2022 | 182 | 105 | 67% | 77 | 70% |
| 2023 | 115 | 69 | 68% | 46 | 54% |
| 2024 | 127 | 89 | 52% | 38 | 71% |
| 2025 | 151 | 80 | 69% | 71 | 62% |

### Conviction Breakdown

| Conf | N | Acc | UP N | UP Acc | DOWN N | DOWN Acc |
|------|---|-----|-------|--------|--------|---------|
| 0.00 | 698 | 64% | 415 | 64% | 283 | 64% |
| 0.40 | 664 | 66% | 391 | 66% | 273 | 66% |
| 0.45 | 645 | 67% | 390 | 66% | 255 | 67% |
| 0.50 | 597 | 67% | 358 | 67% | 239 | 68% |
| 0.55 | 429 | 73% | 237 | 73% | 192 | 74% |
| 0.60 | 385 | 75% | 227 | 75% | 158 | 76% |
| 0.65 | 294 | 80% | 171 | 80% | 123 | 81% |

## O2 — Gap Decomposition (Corrected)

**Timing correction:** model target is same-day close_T vs close_{T-1} (verified 87.5% match).
Feasible no-look-ahead entry: open_T, exit close_T — intraday futures, zero gap risk.

| Conf | N | Open->Close ret | Win% | Dir Acc |
|------|----|------|------|------|
| 0.00 | 698 | +0.309% | 69% | 64% |
| 0.40 | 664 | +0.331% | 70% | 66% |
| 0.45 | 645 | +0.335% | 71% | 67% |
| 0.50 | 597 | +0.336% | 70% | 67% |
| 0.55 | 429 | +0.427% | 75% | 73% |
| 0.60 | 385 | +0.444% | 75% | 75% |
| 0.65 | 294 | +0.501% | 78% | 80% |

**O2 verdict: PASS (futures, open->close).** +0.31%/trade gross, net of ~0.03% futures = +0.28%.
At conf >= 0.60: +0.44%/trade gross across 385 trades/5y. Options (1-3% spread) would eat this.

## Summary

| Test | Result |
|------|--------|
| O1 — Directional symmetry | PASS: DOWN=64%, symmetric, beats baselines |
| O2 — Gap decomposition | PASS: +0.31%/trade open->close, tradeable via futures |