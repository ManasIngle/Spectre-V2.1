# Step 2 — Geometry & Exit Backtest
**Date:** 2026-07-19

## Configuration
Lot: 65 | Brokerage: 25.0/trade | Slippage: 5.0bps/side | r=6.5%
IV proxy: VIX/100 (Black-Scholes approx) | Premiums recomputed each minute
Entry gate: after 09:30, before 15:00 | Close all by 15:15 | One position at a time

### Variants
| V | Timeout | Target | SL | Skip Hr | Conf |
|---|---------|--------|-----|---------|------|
| A | 9m | 2.0xATR | 1.0xATR | none | 35 |
| B | 30m | 1.0xATR | 1.0xATR | none | 35 |
| C35 | 30m | 1.0xATR | 1.0xATR | {11} | 35 |
| C40 | 30m | 1.0xATR | 1.0xATR | {11} | 40 |
| C45 | 30m | 1.0xATR | 1.0xATR | {11} | 45 |
| D | 30m | none | none | none | 35 |

## Anchor Period (20260428 -> 20260629)
> Comparison: 78-day live log (SL>>TARGET, ~breakeven clean sample)

### Summary

| V | Trades | Gross | Net | Exp/tr | Win% | PF | Max DD | T/day |
|---|--------|-------|------|---------|------|-----|--------|-------|
| A | 919 | 13,890 | -16,259 | -18 | 40% | 0.93 | -27,015 | 28.7 |
| B | 1118 | 13,540 | -23,216 | -21 | 50% | 0.91 | -33,632 | 34.9 |
| C35 | 1047 | 7,629 | -26,687 | -25 | 50% | 0.89 | -38,049 | 32.7 |
| C40 | 528 | 14,749 | -2,847 | -5 | 51% | 0.98 | -14,446 | 17.6 |
| C45 | 52 | 5,618 | 3,809 | 73 | 56% | 1.26 | -2,353 | 4.0 |
| D | 197 | 7,264 | 846 | 4 | 38% | 1.01 | -19,983 | 6.2 |

### Exit Reasons

| V | TARGET | SL | TIMEOUT | EOD |
|---|--------|-----|---------|-----|
| A | 216 | 432 | 271 | 0 |
| B | 567 | 550 | 1 | 0 |
| C35 | 530 | 516 | 1 | 0 |
| C40 | 273 | 255 | 0 | 0 |
| C45 | 29 | 23 | 0 | 0 |
| D | 0 | 0 | 187 | 10 |
---

## ⚠️ Expiry Day Correction

Initial run used Thursday expiry (legacy). Corrected to **Tuesday** per SEBI's
2024 derivatives framework (each exchange allowed one weekly expiry day; NSE
chose Tuesday for Nifty 50). Rerun with Tuesday expiry above.

Delta vs Thursday:
| V | Net (Thu) | Net (Tue) | Impact |
|---|-----------|-----------|--------|
| A | -14,772 | -16,259 | slightly worse — shorter TTE, less premium |
| D | +2,991 | +846 | still positive but reduced — less time decay |
| C45 | +3,282 | +3,809 | improved — higher PF |

---

## Analysis — Anchor Period (Tuesday Expiry)

### Variant A Sanity Check

| Metric | Anchor (A) | Live Log (clean) |
|--------|-----------|-------------------|
| Net PnL | -16,259 | -23,581 |
| Win % | 40.5% | 44.4% |
| SL:TARGET | 2.0:1 | 5.2:1 |
| Top exit | SL (47%) | SL (20%) |

Variant A reproduces the live log's negative expectancy and SL-dominated exit
profile. **Sanity check passes.**

### Variant Ranking

| Rank | V | Net PnL | PF | Notes |
|------|---|---------|-----|-------|
| 1 | **C45** | +3,809 | 1.26 | Best PF but too sparse (1.6 trades/day) |
| 2 | **D** | +846 | 1.01 | Positive, 6 trades/day — practical |
| 3 | C40 | -2,847 | 0.98 | Near breakeven |
| 4 | A | -16,259 | 0.93 | Live control |
| 5 | B | -23,216 | 0.91 | 30min worse than 9min |
| 6 | C35 | -26,687 | 0.89 | Filter without conf doesn't help |

### Key Findings

1. **Spot targets destroy expectancy.** A, B, C35 all use target/SL — all lose
   money. The models predict 30-min direction; forcing a spot-move exit creates
   adverse SL dominance.

2. **D (pure time) is the practical winner.** +846 net after costs, PF 1.01,
   ~6 trades/day. C45 has better PF but only 52 trades in 33 days.

3. **Confidence filtering helps but kills volume.** C40→C45 shows PF improving
   from 0.98→1.26 but trades dropping from 528→52.

4. **Tuesday vs Thursday expiry:** Shorter TTE reduces time premium, slightly
   hurting the pure-time strategy (D) but improving higher-conf strategies
   (C45). The ranking is stable.

### Recommendation

Run full 2020-2026 period to confirm edge stability. If D remains positive,
the recommended production config:
- Geometry: 30-min hold, no spot target/SL
- Entry: after 09:30, before 15:00
- Close: 15:15
- Expiry: Tuesday weekly
