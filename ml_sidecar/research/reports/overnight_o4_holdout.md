# Overnight — O4 Holdout Validation

**Holdout:** Apr 2026 (6 trading days)
**Model:** stacked-v3, trained <= 2026-03-31
**OOF baseline (2021-25):** 64.0% dir acc, +0.31% open->close capture

## Accuracy

| Metric | Holdout | OOF |
|---|---|---|
| 3-class | 100.0% | - |
| Dir-only | 100.0% (n=5) | 64.0% (n=698) |
| UP | 100.0% (n=4) | 64.1% (n=415) |
| DOWN | 100.0% (n=1) | 64.0% (n=283) |

## Caveats

- **Sample size: n=6 is too small to draw conclusions.** 100% accuracy on 5 directional trades is consistent with the OOF expectation but a single miss would drop this to 80%.
- **Selection optimism risk:** the model architecture and features were iterated on the 2021-2025 window, and this 6-day holdout may be an easy period.
- **Live VPS comparison unavailable:** only 1 prediction logged in overnight_predictions.csv (Apr 25: predicted DOWN, actual not yet recorded).
- **True forward test requires:** extended data beyond Apr 23 and a genuine future period the model development never saw.

## Per-Day

| Date | Pred | Actual | Correct | P(top) | Intraday |
|------|------|--------|---------|--------|----------|
| 2026-04-01 | UP | UP | Y | 0.84 | -0.96% |
| 2026-04-02 | FLAT | FLAT | Y | 0.43 | +1.47% |
| 2026-04-06 | UP | UP | Y | 0.84 | +0.83% |
| 2026-04-07 | UP | UP | Y | 0.54 | +1.25% |
| 2026-04-08 | UP | UP | Y | 0.84 | +0.60% |
| 2026-04-09 | DOWN | DOWN | Y | 0.47 | -0.56% |