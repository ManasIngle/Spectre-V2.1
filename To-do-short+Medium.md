# Short + Medium ToDo — Spectre

Scope: things doable in **hours to ~1 week**. Each item has expected impact, file pointers, and effort estimate. Sorted by ROI.

---

## P0 — Do this week (biggest P&L unlock)

### 1. Enforce SL/Target on live trades  ⏱ 4–6 hours
**Today's evidence:** Spot crossed the BUY CE 24100 SL at 15:18 (24080 < 24091) but the trade kept showing in the CSV through close. Either we're paper-tracking or the engine stops at signal generation.

**Build:**
- New `PositionTracker` in [services/stability.go](services/stability.go): map of active positions {entry, target, sl, expiry_minute}.
- Each cron tick: for each open position, check `spot >= target` (CE) or `spot <= sl` (CE) → mark exit, log to a new `executed_trades.csv` with entry/exit price/time/reason.
- If StableSignal flips while a position is open, exit the old one before considering the new one.

**Output schema:** `executed_trades.csv`: Date, Strike, Type, EntryTime, EntryPremium, EntrySpot, ExitTime, ExitPremium, ExitSpot, ExitReason (target/sl/timeout/flip), PnLPct, PnLRupees (use Nifty lot 65).

### 2. Add session-time gate on new entries  ⏱ 30 min
In `GenerateTradeSignal` ([services/trade_signals.go](services/trade_signals.go)):
```go
if hourMin >= "14:45" && conf < 55 { rawSig = "NO TRADE" }
if hourMin >= "15:10"              { rawSig = "NO TRADE" }
```
Cuts the theta-trap entries from this morning's audit. Free lunch.

### 3. Loosen conviction filter when models agree  ⏱ 1 hour
In stability engine: drop the 8% prob-gap requirement to 5% when all of {Rolling, Direction, CrossAsset} agree on direction. This would have caught the 10:03–10:46 BUY PE setup that returned ~+50% premium.

Add a config field `MinAgreementCount` (default 3) and `RelaxedProbGap` (default 5.0).

### 4. Daily P&L attribution job  ⏱ 3–4 hours
Cron at 15:35 IST: read today's `option_price_array.csv` + `executed_trades.csv`, produce `daily_pnl_attribution.csv` per strike: BestExitMinute, BestExitPnL, Time-to-MFE, Time-to-MAE, ActualExitPnL, EfficiencyRatio.

This closes the loop — every trade gets graded automatically. Without this, we're flying blind on hold-time tuning.

---

## P1 — Next 1–2 weeks (model + infra)

### 5. Add Indian ADRs to overnight model  ⏱ 1 hour
Edit [ml_sidecar/models/overnight_nifty/data_fetcher.py](ml_sidecar/models/overnight_nifty/data_fetcher.py): add INFY, HDB, IBN, WIT, TTM (all on yfinance, US tickers). Retrain stacked v3. Expected: +2–4pp at conf≥0.55. ~20% of Nifty weight trades overnight in NY — this is the biggest free win.

### 6. Recalibrate Cross-Asset model  ⏱ 4–6 hours
**Audit first:** print feature freshness at predict time — are macro features stale by 5+ hours into session?
**Then either:** (a) decay-weight stale features, (b) inject minute-level vol regime, or (c) restrict cross-asset signal to first 90 min of session only.

### 7. Downweight or drop OldDir from live ensemble  ⏱ 30 min
In [services/ml_sidecar.go](services/ml_sidecar.go) ensemble combination: weight OldDir at 0.3× or remove from `Confidence` calculation entirely. Keep loading it for backtest comparisons.

### 8. Notification system (Telegram bot)  ⏱ 3 hours
Single Go goroutine that watches `executed_trades.csv` for new entries → posts to Telegram channel: "🟢 BUY CE 24100 @ 112.95, target 24145, SL 24091, conf 49.5%". Same for exits. Use `go-telegram-bot-api`. One channel for trades, one for system errors.

### 9. Real `/api/health` endpoint  ⏱ 2 hours
[api/handlers/health.go](api/handlers/health.go) currently doesn't return what the UI expects. Add:
- `online` — count of healthy data streams
- `last_yahoo_fetch_at`, `last_oi_fetch_at` — staleness signals
- `model_loaded` — bool per model
- `streams_failing` — list of names

UI's "Online (0 streams)" then becomes truthful.

### 10. Event blackout calendar  ⏱ 2 hours
Hand-maintained `data/event_calendar.csv`: Date, EventType (FOMC/RBI/Budget/MajorEarnings), MinConfidenceOverride. Stability engine reads it; downgrade signals on event days. ~3 hours, immediate accuracy lift.

### 11. Quantile regression for overnight target  ⏱ 4 hours
In [train_regression_v3.py](ml_sidecar/models/overnight_nifty/train_regression_v3.py): train P25/P50/P75 with `objective='reg:quantileerror'`. Output P25/P75 alongside `predicted_close`. Frontend shows the band; you can size positions by interval width.

---

## P2 — When P0/P1 are shipped

### 12. PurgedKFold for inner CV  ⏱ 2 hours
Replace `TimeSeriesSplit` in [train_rolling_master.py](ml_sidecar/models/train_rolling_master.py) with a de Prado–style PurgedKFold. Won't change live behavior but gives honest hyperparam selection for next retrain.

### 13. Config-extract magic numbers  ⏱ 3 hours
Move all thresholds (35% conf gate, 45% ATM-vs-OTM, 8% gap, hold times, ATR multipliers) into [config/config.go](config/config.go) as a `SignalConfig` struct. Enables A/B tuning and per-regime overrides.

### 14. NSE-direct OHLCV fallback  ⏱ 4–6 hours
We already proxy NSE for OI. Add an OHLCV fetch path so if Yahoo blocks the IP, the system degrades gracefully rather than going dark.

### 15. Multitimeframe view diagnostic  ⏱ 1 hour
Investigate why the table sometimes shows empty rows ("0 streams" + Neutral cells). Likely a Yahoo-fetch chain failure on session-open minutes. Add per-row error reporting in the API response.

### 16. Spec out the position simulator  ⏱ 2 hours design + 1–2 days build
Paper-trading mode where every signal becomes a virtual fill, tracked through to exit. Feeds the same `executed_trades.csv` schema. Compare paper-trading P&L vs hypothetical-perfect-exit P&L weekly.

### 17. Frontend shared API client  ⏱ 2 hours
`frontend/src/api/client.js` with retry, normalized errors, optional response caching. Replace ~12 raw `fetch()` calls in components.

### 18. Refactor cron.go  ⏱ 3 hours
Split into `cron/scheduler.go`, `cron/jobs.go`, `cron/migrations.go`. Currently the file does too much; bugs hide easily.

### 19. Backtest harness uses live CSVs as input  ⏱ 4 hours
[backtest/](backtest/) currently runs against a downloaded ml_trade_logs CSV. Wire it to read directly from `data/system_signals.csv` + `data/option_price_array.csv` so weekly backtests can replay live data without manual exports.

### 20. Volume Backups configured in Dokploy  ⏱ 5 min, do once
Add daily 16:30 IST backup for both `spectre_data` and `overnight_data` volumes via Dokploy UI. Belt-and-suspenders for the persistence work just shipped.

---

## Quick wins parking lot (each <30 min)

- Drop "0 streams" placeholder in DataHealthWidget until real count is wired
- Add `/api/version` returning git SHA + build time → easier to verify what's actually deployed
- Move hard-coded `localhost:8240` fallbacks to a single `SIDECAR_URL` env var
- Log the conviction-engine decision reason to CSV (currently we see in/out but not WHY)
- Add `Edge_Type` column to system_signals: SCALP/SWING — based on confidence + time-of-day
