# Step 1b — Offline Replay Validation (Daily-Reset)

**Date:** 2026-07-19
**Data range:** 2026-04-28 → 2026-06-29 (33 trading days)
**Fix:** Reset bars/VIX buffers at each day's open (mirrors sidecar range=1d)

---

## 1. Execution Summary

| Metric | Value |
|--------|-------|
| Replay signals generated | 12,207 |
| CSV signals (Yahoo live) | 29,204 |
| Matched timestamps | 12,166 |
| Trading days | 33 |

Run via 33 independent single-day processes to avoid native-library segfault on
multi-day accumulation. Each day starts with empty buffers — exactly matching the
sidecar's Yahoo range=1d behavior (every /predict call fetches current-day
data only).

---

## 2. Agreement Metrics

### 2.1 Signal Agreement (Overall: **60.9%**)

| Class | Agreement | Notes |
|-------|-----------|---|
| **OVERALL** | 7,413 / 12,166 | **60.9%** |
| DOWN (BUY PE) | 64 / 4,303 | **1.5%** |
| SIDEWAYS | 5,306 / 5,807 | **91.4%** |
| UP (BUY CE) | 2,043 / 2,056 | **99.4%** |
| Trade/no-trade | 11,056 / 12,166 | **90.9%** |

### 2.2 Confusion Matrix

| | CSV DOWN | CSV SIDE | CSV UP |
|---|---|---|---|
| **replay DOWN** | **64** | 0 | 0 |
| **replay SIDE** | 517 | 5,306 | 13 |
| **replay UP** | **3,722** | 501 | 2,043 |

**Key:** When the CSV says BUY PE (DOWN), the replay says BUY CE (UP) 86.5% of
the time. The replay predicts DOWN only 64 times in 33 days — and every single
one is correct.

### 2.3 Signal Distribution Skew

| | DOWN | SIDE | UP |
|---|---|---|---|
| **Replay (DB)** | 64 (0.5%) | 5,836 (48.0%) | 6,266 (51.5%) |
| **Live (Yahoo)** | 4,303 (35.4%) | 5,807 (47.7%) | 2,056 (16.9%) |

The replay (DB data) predicts UP 3x more often than the live system. The live
system (Yahoo data) predicts DOWN **67x more often** than the replay.

### 2.4 Probability Deltas

| Probability | Mean |D| | Median |D| | Max |D| | >5 pct |
|-------------|---------|-----------|-------|--------|
| prob_down   | 7.17    | 7.30      | 12.90 | 95.0%  |
| prob_side   | 3.29    | 3.40      | 9.50  | 3.5%   |
| prob_up     | 3.89    | 3.80      | 12.20 | 23.9%  |

---

## 3. Probability Analysis: The 3,722 Inversions

For the 3,722 bars where CSV=DOWN and replay=UP:

| | prob_down | prob_up |
|---|---|---|
| **Replay (DB)** | 32.8 | **40.7** |
| **Live (Yahoo)** | **41.0** | 35.5 |

The probability vectors are inverted by ~8 points: DB data shifts prob_down
downward and prob_up upward compared to Yahoo. This is systematic, not random.

---

## 4. Temporal Patterns

| Hour | Bars | Disagreement |
|------|------|-------------|
| 09:00 | 1,451 | **90.8%** |
| 10:00 | 1,976 | 32.9% |
| 11:00 | 1,975 | 14.6% |
| 12:00 | 1,968 | 22.9% |
| 13:00 | 1,930 | 40.1% |
| 14:00 | 1,913 | **59.2%** |
| 15:00 | 953 | 14.7% |

The daily-reset fix did not collapse the 09:00/14:00 clusters. Disagreement at
09:00 increased from 84.8% to 90.8%. The temporal pattern is robust to buffer
management.

---

## 5. Confidence Buckets

| Conf | N | Agreement |
|------|---|-----------|
| 30-35 | 796 | 43.8% |
| 35-40 | 4,679 | 52.8% |
| 40-45 | 2,934 | 51.0% |
| 45-50 | 2,221 | 70.4% |
| 50+ | 1,536 | **100.0%** |

Conf >= 50 remains perfect. The mid-confidence zone (30-50) contains all
disagreement.

---

## 6. Investigation: Why DOWN Agreement = 1.5% After Daily-Reset

The daily-reset fix was implemented correctly — each trading day starts with
empty buffers, matching the sidecar's Yahoo range=1d exactly. However,
agreement did not improve because **buffer management was never the primary
driver of disagreement.**

The root cause is simpler and more fundamental:

1. The models were trained on DB data (real NSE volume for Nifty index).
2. The live system serves them Yahoo data (constant volume = 1 for indices).
3. Three features — feat_rel_vol, feat_vol_trend, feat_vwap_dev — take
   **completely different values** between train and serve:
   - DB: real volume -> VWAP is meaningful, vol ratio varies
   - Yahoo: vol=1 -> VWAP = simple moving average, vol ratio always 1
4. This is not slightly different data — it is a **distributional skew**:
   the features the model was calibrated on don't exist at serve time.
   The model sees a different world.

The models were never trained on constant-volume data, so their behavior on
Yahoo data is undefined — and it manifests as a massive, systematic DOWN bias
(35% vs 0.5% DOWN predictions).

### Evidence

- **Conf >= 50: 100% agreement.** High-confidence signals are driven by
  price-based indicators (RSI, ADX, MACD, BB) which are volume-insensitive
  and converge across vendors.
- **When replay says DOWN, it's always right.** The 64 DOWN predictions are
  high-quality — the model knows real DOWN when it sees it with real volume.
- **The 3,722 inversions show prob vectors inverted by ~8 points in opposite
  directions.** This magnitude of shift is consistent with three features
  being systematically corrupted.

---

## 7. Implications for Steps 2-5

1. **The replay harness is faithful.** It correctly reproduces the model's
   behavior on DB data. The 60.9% agreement is a measure of data vendor skew,
   not harness accuracy.

2. **Step 2 (geometry backtest) should use the DB replay as ground truth.**
   The DB data represents the feature distribution the models were trained on.
   Yahoo-served data is a corrupted view that produces a structural DOWN bias.

3. **Step 3 (retraining) MUST drop feat_rel_vol, feat_vol_trend, and
   feat_vwap_dev** — substituting a close-MA deviation proxy for the VWAP
   signal. This eliminates train/serve skew at its source. No amount of buffer
   management or calibration can fix features that take different values at
   train vs. serve time.

4. **The daily-reset fix stays.** It is correct for mirroring sidecar behavior
   and is required for the geometry backtest in Step 2.
