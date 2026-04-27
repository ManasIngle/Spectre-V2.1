# Large Initiatives ToDo — Spectre

Scope: multi-week to multi-month efforts. These are the bets that take Spectre from "useful research tool" to "production-grade signal system you'd run real money on."

Sorted roughly by leverage on the core mission (**perfect intraday scalping + trading signals**).

---

## A. The Execution & Feedback Layer (highest leverage)

### A1. Real broker integration (paper → live)
**What:** Direct integration with Zerodha Kite or Upstox API. Paper-trading mode first (mirror executions, track virtual P&L), then a feature-flagged live mode.

**Why:** Today the entire trade lifecycle is synthetic — entries logged, no real fills, no real exits, no slippage measurement. Without real fills you cannot ever know if the system would have made money. Backtests are not enough; broker order rejection patterns and intra-bar fills only show up live.

**Scope:**
- Broker abstraction layer in Go (`services/broker.go`) supporting paper + Zerodha + Upstox
- Order state machine: Pending → Open → Filled → Closing → Closed/Rejected
- Reconciliation: every minute, fetch broker positions, match against internal state
- Position sizing module — Kelly fraction or fixed-fractional, capped per-trade
- Daily reconciliation report

**Effort:** 3–4 weeks. **Risk:** high (real money). Do paper for 2 weeks first.

### A2. Closed-loop signal grader
**What:** Every signal generated gets a grade once the day closes (Win/Loss/Suppressed-but-correct/Suppressed-but-wrong). Roll up weekly into a model scorecard. Surface in the UI.

**Why:** Right now we audit manually after the fact. A continuous grader gives us a daily P&L attribution by model + by signal-type + by time-of-day. This is what tells us whether changes are improving things or making them worse.

**Scope:**
- Cron at 15:35 IST processes today's `system_signals.csv` + `option_price_array.csv` + `executed_trades.csv`
- Per-signal label: actual move at +5/+10/+15/+30 min, theta-adjusted P&L on hypothetical option entry
- Stored in `signal_grades.csv` (date, signal_id, raw_signal, suggested_strike, taken, theoretical_pnl_pct, actual_pnl_pct)
- Weekly Sunday job aggregates → `model_scorecard.csv` (per-model precision/recall, win rate, avg P&L, sharpe by hour)

**Effort:** 1–2 weeks. **Dependency:** the Option Price Array tracker (already shipped).

### A3. Hold-time optimization from real data
**What:** Once A2 is running, regress optimal hold time against signal features (confidence, model agreement, VIX regime, time-of-day). Replace today's hard-coded hold-time table with a learned policy.

**Why:** Today's table is hand-tuned from a one-time backtest. With weeks of real data, the policy should adapt. This is the kind of feedback loop that compounds.

**Effort:** 1 week (after A2 has 30+ days of data).

---

## B. Risk Management & Capital Allocation

### B1. Real risk module
**What:** A `services/risk.go` that owns: max daily loss, max position size, max consecutive losses, time-in-market limits, correlation caps if multi-leg, max drawdown circuit breaker.

**Why:** Right now there's no concept of risk. A bad day could blow through everything because nothing stops the system from taking the next trade.

**Scope:**
- Risk config: daily_max_loss_pct, max_consec_losses, max_concurrent_positions
- Risk state (persisted): today's realized P&L, today's open exposure, last-N-trade outcomes
- Pre-trade gate: every signal goes through `risk.AllowTrade(signal)` before the stability engine
- Daily reset at 09:00 IST; circuit-breaker reset requires manual unlock

**Effort:** 1–2 weeks.

### B2. Multi-leg + hedged strategies
**What:** Beyond naked CE/PE, support spreads (bull call, bear put), iron condors on high-VIX days, cash-secured puts.

**Why:** Naked options are unforgiving and theta-sensitive. Spreads cap losses and can profit from chop. Once the system is conviction-aware, structuring should match conviction level.

**Effort:** 4+ weeks. Material rework of signal generation + position tracking.

### B3. Portfolio-level Greeks tracking
**What:** Show net delta/gamma/theta/vega across all open positions. Alert when net delta exceeds tolerance.

**Why:** Single-trade thinking misses portfolio risk. Multiple BUY CE positions across strikes have correlated delta exposure.

**Effort:** 1 week (math is straightforward; OI chain already gives us strike-level data).

---

## C. Data Pipeline Maturation

### C1. Multi-source data redundancy
**What:** Three data sources for OHLCV (Yahoo, NSE-direct, broker WebSocket) with automatic failover and divergence detection.

**Why:** Yahoo blocks have caused multiple production incidents. A broker WebSocket gives sub-second 1m bars and is the most reliable source for live trading. Divergence detection catches stale-cache issues.

**Scope:**
- Source-of-truth ranking
- Health monitor per source (last-success-ts, error rate)
- WebSocket consumer (Zerodha or Upstox) writing 1m bars to a shared in-memory ring buffer
- Cross-source price diff alerting

**Effort:** 3 weeks. **Dependency:** broker integration (A1).

### C2. Tick-level data archive
**What:** Store every minute's OI chain snapshot, every signal, every execution, every option price → cold storage (Parquet on S3 / B2). Build a 6-month rolling archive.

**Why:** Today's CSV-on-disk model works for one day. For training v4 models, walk-forward backtests, regime analysis — we need years of replayable data with the same shape as production. Parquet + DuckDB makes this analyzable in seconds.

**Scope:**
- Daily rotation: yesterday's CSVs → Parquet → S3
- Schema versioning
- Replay tool: re-run any historical day through the live signal generator

**Effort:** 2–3 weeks.

### C3. FII/DII + GIFT Nifty pipelines
**What:** Persistent scrapers for the two biggest known data gaps. Either paid feed (Refinitiv, Bloomberg) or robust scraper with proxy rotation + change-detection.

**Why:** Documented in MODELS.md as the highest-impact missing inputs. Expected lift on overnight model: 3–5pp directional accuracy at high-conviction.

**Effort:** 2 weeks (scraper) or 1 day (paid feed setup, if budget allows).

---

## D. Model Sophistication

### D1. Regime-aware ensemble routing
**What:** Detect market regime (trending up / trending down / chop / high-vol / news-driven) per minute. Route signal generation to a regime-specialized model rather than always-the-same ensemble.

**Why:** A model trained globally is mediocre everywhere. A regime-router + 4 specialists usually beats a single global model by 3–5pp accuracy.

**Scope:**
- Regime classifier (HMM or simple z-score regime on VIX + 20m realized vol + ADX)
- Train 4 specialist models, one per regime (same features, different data subsets)
- Ensemble weights become regime-conditional

**Effort:** 3–4 weeks.

### D2. Sentiment + news pipeline
**What:** Real-time financial news ingestion (RSS + scraping) → FinBERT or GPT-4 sentiment scoring → as a model feature and as a blackout trigger for breaking news.

**Why:** Models are blind to "RBI just announced surprise rate hike." Even crude sentiment beats nothing. Long-term, individual headline impact estimation enables better intraday prediction.

**Effort:** 4+ weeks.

### D3. Order-flow imbalance from L2 data
**What:** If a broker WebSocket gives full order book, derive order-flow imbalance, large-trader detection, microstructure features. These are the signals professional HFT desks live on.

**Why:** Currently we infer from price. Direct order-flow features have substantially more signal-to-noise. Expected: 5–10pp accuracy lift on scalping horizons (1–5 min).

**Effort:** 6+ weeks. **Dependency:** broker WebSocket (A1/C1).

---

## E. Observability & Operations

### E1. Prometheus + Grafana dashboard
**What:** Metrics export from Go + Python, dashboards for: model latency, prediction confidence histogram, signal generation rate, fetch error rates, sidecar memory/CPU, cron lag, P&L curve.

**Why:** When something breaks at 10am, you need to know in 30 seconds, not at end of day. CSV-grepping is fine for backtest, terrible for ops.

**Effort:** 1–2 weeks.

### E2. Structured logging + log aggregation
**What:** Replace `log.Printf` with structured JSON logs (slog in Go, structlog in Python). Ship to Loki or Better Stack.

**Why:** Searchable logs, alertable patterns, post-incident analysis becomes possible.

**Effort:** 1 week.

### E3. CI/CD with model regression tests
**What:** GitHub Actions: on PR → run unit tests + a "golden day" backtest (e.g. replay 2026-04-15 through current code, assert outputs match within tolerance). Block merge if regressed.

**Why:** Today, any commit could silently break the trade pipeline. Once you have real money behind it, this is non-negotiable.

**Effort:** 2 weeks.

---

## F. Frontend & UX

### F1. Trade journal UI
**What:** A "Journal" tab showing every executed trade with: chart of spot during the trade, entry/exit/SL/Target lines, premium evolution, post-trade analysis (was it the optimal exit window? what would 5min later have done?).

**Why:** Visualizing trades is how you build intuition for what works. Better than CSV-grepping.

**Effort:** 1 week.

### F2. Live position panel in Cockpit
**What:** Persistent panel in Cockpit showing current open positions, real-time P&L, time-to-stop-out, mini-chart per position.

**Why:** Today the Cockpit shows the *signal*, not the *position*. Different concerns; both matter.

**Effort:** 3–4 days.

### F3. Mobile-friendly view
**What:** Cockpit and Trade Signals views responsive for phone. Or a separate minimal mobile route.

**Why:** Active trading happens away from desk. A phone view of "current signal + open positions" is invaluable.

**Effort:** 1 week.

---

## G. Research / Strategy

### G1. Build a strategy library, not a single signal
**What:** Today: one model → one signal type (BUY CE / BUY PE / NO TRADE). Build: a library of 8–12 distinct strategies (momentum scalp, mean-reversion fade, gap-fill, opening-range breakout, end-of-day closing-imbalance, OI-shift play, etc.). Run all in parallel as paper-trades; surface the highest-conviction one in UI.

**Why:** Diversification of strategy logic is more robust than diversification of feature set within one strategy. Different regimes favor different strategies.

**Effort:** 8+ weeks. This is a months-long research arc.

### G2. Reinforcement learning on hold-time policy
**What:** Once A2 + A3 are mature with months of data, train an RL policy on the hold-time decision (continuous action: "hold X more seconds"). Reward is theta-adjusted P&L.

**Why:** Optimal hold time depends on dozens of micro-features that hand-coded rules can't capture. RL on real data eventually beats every rule-based exit.

**Effort:** 4+ weeks (modeling) + months of data collection.

### G3. Monthly research cycle
**What:** Standing process — first weekend of each month, rerun walk-forward training on last 12 months, compare against incumbent, deploy if better. Document changes.

**Why:** Models drift. Markets change. Without a discipline, you ship one model and it slowly decays.

**Effort:** 1 weekend setup, ongoing.

---

## Suggested 6-month sequencing

| Month | Theme | Headline deliverable |
|---|---|---|
| 1 | Plug execution leaks | Real SL/Target, broker paper-trade, signal grader |
| 2 | Risk + alerts | Risk module, Telegram alerts, Prometheus dashboards |
| 3 | Data unlock | ADRs in overnight, FII/DII pipeline, NSE-direct fallback |
| 4 | Live trading (small) | Paper → live with tiny size, daily reconciliation |
| 5 | Model v4 | Regime-aware ensemble, retrain everything with new features |
| 6 | Strategy library | Run multiple strategies in parallel, conviction-weighted UI |

The core principle behind this ordering: **fix what we have before adding new things**. Today's system is bleeding through the execution layer. Plugging that is worth more than any model upgrade.
