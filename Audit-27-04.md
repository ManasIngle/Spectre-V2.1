# Spectre Full-System Audit — 2026-04-27

Scope: signal quality, execution layer, data pipeline, observability, code health. Lens: "what blocks us from a production-grade intraday scalping + trading system."

---

## 0. Executive verdict

The ML core is solid. The **execution layer and feedback loops are where money is being left on the table**:
- Stability engine is over-suppressing (today: 1 trade in 5.5h, while morning DOWN call would've returned ~+₹3,000/lot)
- SL appears unenforced in live data (spot crossed SL, no exit recorded)
- No time-of-day filter → late-session entries die to theta
- No automated post-trade analytics — every audit so far has been manual

Roughly: **the model is right ~55% of the time, the trade-layer is right less often than that.** Fix the trade layer first; then re-tune models.

---

## 1. Critical (signal-quality + execution)

### 1.1 SL enforcement looks broken
**Evidence:** Today's BUY CE 24100 with SL 24091. Spot hit 24080.80 at 15:18 — clearly below SL — and the CSV continues to show the trade open through 15:30.

**Where to look:** [services/stability.go](services/stability.go), [services/trade_signals.go](services/trade_signals.go). The hold-time logic appears to track the position's lifecycle, but no clear SL trigger in the cron flow.

**Why it matters:** Without SL enforcement, downside is unbounded. Every slippery day the stability engine prevented a loss masks the fact that the layer doesn't actually protect us.

### 1.2 No time-of-day filter on entries
**Evidence:** Today's only trade fired at 15:00. ATM CE with 30 min until close = pure theta exposure. Even with a correct +0.8 spot direction, premium fell 5%.

**Fix scope:** Add a session-time check in `GenerateTradeSignal`: after 14:45 IST require `confidence ≥ 55%`; after 15:10 block all new entries.

### 1.3 Conviction filter too tight in chop-but-trending phases
**Evidence:** 10:03–10:46 — sustained BUY PE signals at 35–37% confidence with 4–7% prob gap. All suppressed. Spot fell 110 pts in that window. Optimal entry would've returned ~+50% premium.

**Fix scope:** Lower the prob-gap requirement from 8% → 5% when *all of* {Rolling, Direction, CrossAsset} agree on direction, OR when the signal has fired ≥ 3 consecutive minutes.

### 1.4 Cross-Asset + Scalper models persistently bullish
**Evidence:** Today, `CrossAsset_Up` and `Scalper_Up` stayed at 40–55% even during the 110-pt morning sell-off. They never confirmed the BUY PE side, which is partly why conviction filter never fired.

**Hypothesis:** Stale macro features dominating. Cross-asset uses BankNifty spread / overnight US data — those don't change intraday, so the model's UP bias gets baked in for the whole session if the macro setup is bullish.

**Fix scope:** (a) audit feature freshness in [ml_sidecar/sidecar.py](ml_sidecar/sidecar.py); (b) decay weight on stale features; (c) retrain with intraday volatility as additional input.

### 1.5 OldDir (1h) model is noise at minute frequency
**Evidence:** OldDir_Signal flips between BUY CE / BUY PE / NO TRADE within 5-minute windows despite being a 1-hour-horizon model. Probabilities swing 15–20 pts minute-to-minute.

**Fix scope:** Either (a) cache the 1h prediction for 30 min between recomputes, (b) downweight its vote in the ensemble to 0.5×, or (c) drop it entirely from the live signal path (keep for backtest analysis).

### 1.6 No automated P&L attribution
**Evidence:** Every audit done so far has been manual (spot trajectory inspection, mental math on premium changes). The just-added Option Price Array CSV is the right substrate but nothing reads it back.

**Fix scope:** Daily-close cron job that, for each suggested strike, computes: best exit window, max favorable, max adverse, time-to-MFE/MAE. Persist to `daily_pnl_attribution.csv`.

---

## 2. Important (data + model integrity)

### 2.1 Inner CV folds have boundary leakage
Rolling master uses TimeSeriesSplit inside RandomizedSearchCV. Each fold's train/val boundary still has the 30-row purge issue (only the outer 80/20 split is purged today).

**Fix:** Implement de Prado's `PurgedKFold` splitter. ~50 lines. Won't change deployed model behavior much, but cleaner CV → more honest hyperparameter selection.

### 2.2 Sidecar uses Yahoo only, no fallback
Single point of failure. Yahoo can rate-limit or change response shape (already happened twice — UA workaround in commit `a9ad344`, brotli fix in `64d833f`).

**Fix scope:** Add NSE-direct fetch as fallback (we already do this for OI). Could also add Upstox/Zerodha API if a paid feed is acceptable.

### 2.3 No event-day awareness
FOMC, RBI policy, Budget, mega-cap earnings days have systematically different volatility regimes. The current models treat them as ordinary days. Almost certainly the ~25% misses at high-confidence are clustered there.

**Fix scope:** Static event calendar (manually maintained) → block or downgrade signals on those days. Long-term: scrape from RBI/SEC calendars.

### 2.4 Overnight model: known data gaps
Documented in [ml_sidecar/MODELS.md](ml_sidecar/MODELS.md):
- **GIFT Nifty** — closest free signal we don't have
- **FII/DII flows** — biggest expected lift (~3–5pp at high-confidence)
- **Indian ADRs (INFY/HDB/IBN/WIT)** — covers ~20% of Nifty weight, trades overnight in NY, on yfinance, **literally one hour of work to add**

### 2.5 Hard-coded magic numbers
Throughout the trade-signal layer:
- 35% confidence threshold for any signal
- 45% confidence for ATM vs OTM strike selection
- 8% prob gap for stability engine
- ATR multipliers, expected-move scaling
- Hold-time table (8/10/15/25 min)

These should live in a single config struct (probably in [config/config.go](config/config.go)) so they can be tuned per-regime or A/B'd.

---

## 3. Infra + observability

### 3.1 Health endpoint is misleading
[api/handlers/health.go](api/handlers/health.go) returns `status: ONLINE` based purely on sidecar reachability. The UI shows "Online (0 streams)" because `health.online` field doesn't exist. Doesn't tell you if Yahoo's working, OI is fresh, etc.

**Fix scope:** Real health: per-data-source last-success timestamp, count of failed fetches in last 5min, ML model accuracy on rolling validation window.

### 3.2 No alerting
If the sidecar dies at 11am, you find out at end of day. No Telegram/email/push for: model failures, repeated fetch errors, stability engine resets, high-conviction signals.

### 3.3 No metrics aggregation
Logs go to stdout (Docker captures them) and CSV. No Prometheus/Grafana setup. Hard to answer "what was confidence distribution last week" without grepping CSVs.

### 3.4 Single Yahoo IP exposure
Container's IP gets blocked → 5+ min recovery cycle. No rotating proxy / multi-IP pool. Past commits show ongoing fight (UA spoofing, brotli, etc.).

### 3.5 Persistence done (today)
✓ Named Docker volumes for `spectre_data` + `overnight_data` shipped in commit `979926f`.

---

## 4. Code health

### 4.1 sidecar.py is 1300+ lines, mixed concerns
Currently does: model loading, feature engineering, HTTP routing, OHLCV proxy, OI proxy, scheduler, multiple model paths. Refactor into modules: `loaders.py`, `features.py`, `endpoints/`, `proxies.py`, `scheduler.py`.

### 4.2 No unit tests
Critical paths (stability engine, signal generation, feature extraction) have no test coverage. A single bad commit could silently break the trade pipeline. Even a few golden-output tests would catch most regressions.

### 4.3 cron.go does too much
Schedules + CSV migration + signal generation + (now) option-array logging. Split scheduling into its own package; keep the cron loop tiny.

### 4.4 Multiple "log to CSV" helpers, no shared abstraction
`logSignalToCSV`, `LogOptionArraySnapshot`, scalper CSV writer (in sidecar) — three slightly-different patterns. One `csvAppender` helper would centralize header migration, locking, error handling.

### 4.5 Frontend has no shared API client
Every component does `fetch('/api/...')` directly. No retry, no error normalization, no shared types. A 5-minute extraction into `api/client.js` would clean this up.

---

## 5. What's actually working well

Worth saying explicitly:
- **Inference parity** between training and production for the rolling master is genuinely correct (1m bars → rolling 5m windows in both)
- **Sidecar TLS workaround** is a clever solution to a hard problem
- **Overnight v3 stacked ensemble** with isotonic calibration is production-quality work — 75–79% directional at high-conviction is real alpha
- **Option Price Array** (today's add) is exactly the right kind of feedback substrate
- **Persistence migration** to named Docker volumes is now correct for Dokploy
- **CSV-as-source-of-truth** for signals/predictions is great for offline analysis

---

## 6. Risk-ranked summary

| # | Issue | Blast radius | Effort | Priority |
|---|---|---|---|---|
| 1.1 | SL not enforced | $$ direct loss | M | **P0** |
| 1.2 | Late-session entries | $ recurring | S | **P0** |
| 1.3 | Conviction filter too tight | $$ missed gains | S | **P0** |
| 1.4 | CrossAsset stale bias | $ signal noise | M | P1 |
| 1.5 | OldDir minute-noise | $ signal noise | S | P1 |
| 1.6 | No P&L attribution | analytics | M | P1 |
| 2.4 | ADR features missing | $ accuracy | S | P1 |
| 3.2 | No alerting | reliability | M | P1 |
| 2.3 | No event blackout | $ accuracy | S | P2 |
| 2.1 | Inner CV leakage | hygiene | S | P2 |
| 3.4 | Yahoo single point | reliability | L | P2 |
| 4.x | Code health | velocity | L | P3 |

Three changes (1.1, 1.2, 1.3) are <1 day combined and would be the single biggest P&L unlock. **Start there.**
