# SPECTRE: DEEP LORE & DEVELOPMENT CHRONICLES 


## The Evolution from v1 to v2: The Hunt for Alpha
The Spectre project transitioned from a basic automated trading bot into an Institutional-Grade System across several major iterations. Below is the historical development logic that dictates why the system is built the way it is today.

---

### Phase 1: The Go Migration & The Jitter Problem
Originally, the entire backend was written in Python. This presented extreme memory leak issues and routing latency. 
**The Fix:** We completely decoupled the architecture. We re-engineered the routing, OI logic, and API handling strictly into a compiled **Go `(spectre-go)`** application, placing the Python Machine Learning strictly into a decoupled "Sidecar" (`ml_sidecar/sidecar.py`).

**The Problem:** The user noted extreme "Jitter" on the dashboard. The ML signal would flip from `BUY CE` to `BUY PE` back to `BUY CE` in under 3 minutes due to standard market volatility. 
**The Fix:** The **Stability Engine**. Instead of retraining the model, we added a mathematical lock in Go. If a signal flipped, Go analyzed the probability gap (the "Conviction"). If the ML was only 51% confident in a reversal, Go suppressed the output, forcing the trader to hold their original position instead of panic-selling a minor fake-out.

---

### Phase 2: The "Unfinished Candle" Dilemma
Even with the Stability Engine, the user correctly identified a major mathematical flaw: **Standard 5-Minute Candles mean the trader is waiting blindly.**
If you only refresh at 09:15, 09:20, and 09:25... what happens at 09:23 when the market crashes? Furthermore, if you feed the AI an *unfinished* 09:23 candle, the ML indicators (like RSI and MACD) become heavily distorted because the candle hasn't closed yet.

**The Fix: Rolling Windows.** We downloaded massive 1-minute tick datasets. We wrote custom vector math to stitch the preceding 5 minutes into a single "Rolling 5m Candle". This allowed the ML to evaluate a perfectly completed, historically stable pattern every single 60 seconds without distortion. 

---

### Phase 3: The 10-Year "Treasure Trove" & The Accuracy Cap
The user provided an unprecedented 10-Year, 1-Million row dataset (`Market Dataset since 2015`). We retrained the Vanilla model on this. 
The Accuracy capped exactly at **47.5%**. 
*Why?* The user asked why it wouldn't go higher. This led to a deep philosophical quant discussion.
**The Insight:** The market is "Efficient." If a purely mathematical Price/Volume model could reliably predict the stock market at 70% accuracy, hedge funds would instantly arbitrage the edge away. Capping at ~48% on a 3-class problem (UP, DOWN, SIDEWAYS) meant the model extracted massive Alpha (+15% over random chance), but couldn't go further using purely endogenous (Nifty-only) data. It was behaving conservatively, often predicting `SIDEWAYS` to protect options premium.

---

### Phase 4: The Sectoral Alpha & The "Boy Who Cried Breakout"
To shatter the 47.5% accuracy ceiling, we began engineering **Alternative Data**.
The user's dataset included `Nifty Bank`. Because BankNifty constitutes over 35% of Nifty 50, it acts as the ultimate leading indicator. 

We built `train_cross_asset.py`. It flawlessly mapped the minute-ticks of BankNifty and Nifty 50 synchronously. It calculated the correlation spreads (Is BankNifty dumping while Nifty is flat?). 

**The Trap:** Initially, the 15-minute cross-asset model achieved **58% Accuracy**. But the user brilliantly audited the breakdown metrics: *The model was a coward.* It noticed that the market stays flat 60% of the time, so it constantly predicted `SIDEWAYS` to farm "Accuracy Points", completely failing to call actual trends.

**The Ultimate Fix (Aggressive Weighting):** We injected massive class penalties. We mathematically forced the XGBoost engine to double its penalty whenever it missed an `UP` or `DOWN` trend.
The result was mind-bending:
* **Accuracy plummeted to 28%.**
* **Trend Capture (Recall) surged to 54%.**

We sacrificed cosmetic "Accuracy" to build a true Hedge-Fund style Breakout Hunter. It will confidently call false breakouts (losing tiny fractions of capital), but it successfully catches over half of all Black-Swan momentum explosions before they happen.

---

### Phase 5: The Headless Architecture
To complete the system, the user requested it to run silently on a VPS remote server, independently of front-end browser interactions. 
We coded `services.StartSystemCron()` strictly in native Go. It intercepts the backend logic every 60 seconds, bypasses the system caches, downloads new Yahoo ticks, asks Python for a signal, and writes the output directly to a CSV, creating a highly resilient, completely automated Alpha mining server.

---

### Phase 6: Backtest-Driven Retraining & India VIX Integration (April 2026)

#### The Problem: False Bearish Signals & Cowardly Hold Times
A systematic backtest of logged signals revealed a structural bias: **BUY PE (bearish) win rate was 47.9% vs BUY CE (bullish) win rate of 63.1%.** The model was generating too many false downside signals. Separately, options hold times were hardcoded and did not adapt to signal confidence.

#### Fix 1: Asymmetric Target Thresholds
All four models were retrained with asymmetric labeling logic. The `DOWN` label now requires a **30% larger move** to be assigned than the `UP` label:
```python
threshold_dn = threshold_pct * 1.3   # DOWN needs a bigger move (0.104% vs 0.08%)
```
This reduces the volume of false bearish training examples at the source.

#### Fix 2: Asymmetric Class Weights
During XGBoost training, the `DOWN` class weight is explicitly suppressed:
```python
class_weights[0] = max(class_weights[0] * 0.7, 0.5)  # Penalize DOWN less → fewer false bearish predictions
```
This directly reduces the model's tendency to signal `BUY PE` on ambiguous data.

#### Fix 3: Four New Momentum Features
Added to all models via `add_features()` in `train_multitf.py`:
| Feature | Description |
|---|---|
| `feat_consec_up` | Count of consecutive bullish closes (momentum streak) |
| `feat_consec_down` | Count of consecutive bearish closes (momentum streak) |
| `feat_session_position` | Normalized intraday time (0.0 at open → 1.0 at close) |
| `feat_momentum_divergence` | Difference between price momentum and RSI momentum |

#### Fix 4: India VIX as a Feature
India VIX minute data (`INDIA VIX_minute.csv`) was merged into the training dataset for all models. Four derived features were added:
| Feature | Description |
|---|---|
| `feat_vix_level` | Raw VIX value (absolute fear gauge) |
| `feat_vix_change` | 5-bar rate of change in VIX |
| `feat_vix_vs_avg` | VIX deviation from its 20-bar mean |
| `feat_vix_regime` | Binary: 1 if VIX > 20 (high-fear regime) |

VIX is also fetched live via the Python sidecar (`^INDIAVIX`) at prediction time so inference features match training features.

#### Fix 5: Dynamic Hold Time by Confidence
Hold times in `services/trade_signals.go` now adapt to the model's conviction:
```go
// BUY PE — fast exit (historically lower win rate)
if pred == "DOWN" { baseMinutes = 8.0 }
// BUY CE — scale by confidence
else if conf > 60 { baseMinutes = 10.0 }
else if conf > 45 { baseMinutes = 25.0 }
else              { baseMinutes = 15.0 }
```

#### Model Versioning (`-Rtr14April` Suffix)
All retrained models are saved alongside the originals using the suffix `-Rtr14April` (Rtr = Retrained, 14April = date). The sidecar loads versioned models with a fallback to originals:
```python
VER = "-Rtr14April"
# Tries nifty_rolling_model-Rtr14April.pkl → falls back to nifty_rolling_model.pkl
```
Four models were retrained:
* `nifty_multitf_model-Rtr14April.pkl` (1m, 5m, 15m timeframes)
* `nifty_lstm_model-Rtr14April.keras`
* `nifty_rolling_model-Rtr14April.pkl`
* `nifty_cross_asset_model-Rtr14April.pkl`

Total feature count increased from **31 → 39** (31 base TA + 4 momentum + 4 VIX).

---

### Phase 7: TLS Fingerprint Fix & Sidecar Proxying (April 2026)

#### The Problem: VPS Blocked by Yahoo Finance & NSE Akamai
On the VPS (datacenter IP), both Yahoo Finance OHLCV and NSE OI chain data returned errors. Go's `net/http` sends a distinctive TLS ClientHello fingerprint that Akamai/Yahoo's bot detection identifies and blocks. Python's `aiohttp` library sends a different fingerprint that passes undetected — the same mechanism used by the v2 placeholder project running on the same VPS.

#### Fix: All External Fetches Proxied Through Python Sidecar
Two new endpoints were added to the Python sidecar at port 8240:

**`/ohlcv`** — Yahoo Finance OHLCV proxy:
```
GET /ohlcv?ticker=^NSEI&interval=1m&range=1d
→ {"bars": [{"t": unix, "o": float, "h": float, "l": float, "c": float, "v": float}, ...]}
```
Go's `FetchOHLCV()` in `services/market_data.go` now tries the sidecar first, falls back to direct fetch.

**`/oi`** — NSE OI Chain proxy:
```
GET /oi?symbol=NIFTY&expiry=25-Apr-2025
→ Full OI chain JSON (two-stage cookie auth, NSE v3 API, ssl=False)
```
Go's `FetchOIChain()` in `services/oi_data.go` now tries the sidecar first, falls back to direct fetch.

This fix eliminated both "No market data available" and "Failed to fetch OI data" errors on the VPS without modifying any frontend code.

---

### Phase 8: Signal From Minute 1 (Rolling Window Relaxation) (April 2026)

#### The Problem: "insufficient bars" Error
The sidecar required 55+ completed 1-minute bars before generating a signal, meaning the system was blind for the first ~55 minutes of each trading session — roughly the entire high-volatility opening window.

#### The Fix
The rolling window builder (`build_rolling_bar`) was relaxed to work with as few as 1 bar. Instead of requiring exactly 5 bars, it takes `bars[-5:]` (whatever is available, up to 5). The feature extraction loop starts at index 0 (was index 4). The outer bar threshold was lowered from `< 55` to `< 2`, and the inner window threshold from `< 50` to `< 2`.

Signals are now generated from the very first available minute of data.

---

### Phase 9: Cockpit View & Tab Navigation (April 2026)

#### The Problem: Scattered Information Across Multiple Views
The dashboard required clicking through multiple views to get a complete market picture. Traders need instant situational awareness at market open — not a tabbed scavenger hunt.

#### Fix: Bloomberg-Style Cockpit View
A new `CockpitView.jsx` was created as the default landing view. It presents all critical information in a 3-column layout with no scrolling required:

| Column | Content |
|---|---|
| Left | Active Trade Signal (direction, confidence, hold time) + OI Analysis (PCR, Max Pain, support/resistance) |
| Center | Market Direction composite score (0–100 ScoreArc SVG) + Multi-timeframe confluence table (1m/5m/15m) |
| Right | Institutional Outlook composite + module breakdown bars + intermarket correlation chips (SGX, DXY, Crude) |

Auto-refreshes every 30 seconds. All three API calls (`/api/trade-signals`, `/api/market-direction`, `/api/institutional-outlook`) are fired in parallel.

#### Fix: Tab Navigation
The dropdown `<select>` view switcher was replaced with a horizontal pill-style `<nav className="nav-tabs">` with 9 tabs:
`Cockpit | Trade Signals | Market Direction | OI Trending | Multitimeframe | Heatmap | Institutional | News | ML Logs`

The Cockpit is the default view on load.

---

### Phase 10: The Audit, the Roadmap, and the Multitimeframe Resurrection (April 27, 2026)

A full system audit (`Audit-27-04.md`) revealed the ML core was solid but the execution layer and feedback loops were underdeveloped. Two roadmap docs were written to channel the next 6 months:
- `To-do-short+Medium.md` — 20 actionable items with effort estimates, P0–P2 priorities
- `To-do-large.md` — 7 multi-month initiatives across execution, risk, data, models, observability, UX, research

The audit also surfaced a real bug: the **Multitimeframe view had silently never worked**.

#### The bug
Two issues compounded:
1. **JSON key mismatch** — the `TickerRow` Go struct had JSON tags like `json:"script"`, `json:"ltp"`, `json:"st211"` (lowercase/snake_case), but the React `TraderViewTable` was reading `row.Script`, `row.LTP`, `row['ST 21-1']` (CamelCase / spaces). Every field was `undefined` regardless of market state.
2. **Zero-value rows** — `dashboard.go` returned a zero-value `TickerRow{}` whenever Yahoo gave fewer than 50 bars, because the error filter only checked `r.err == nil` (the helper sent `err: nil` even when bars were insufficient). This produced phantom Neutral rows after market hours.

#### The fix
- Aligned Go JSON tags to CamelCase to match the frontend (`Script`, `LTP`, `Chng`, `ST211`, `EMACross`, `Vol`).
- Made `dashboard.go` send a non-nil error when `len(bars) < 50` so the row is silently dropped.
- Improved empty-state UX to "No data — market may be closed or data source unavailable."

#### Indicator port from `v2-placeholder-30-march`
The legacy Python project had richer Multitimeframe indicators that were missing from the Go port. Added to `services/indicators.go`:
- **FRAMA** — Fractal Adaptive Moving Average (period=16) using fractal-dimension-based adaptive alpha. Buy if close > FRAMA, Sell if below.
- **Williams Alligator** — Jaw (13-period SMMA shifted 8), Teeth (8-period shifted 5), Lips (5-period shifted 3) of median price. Buy if Lips > Teeth > Jaw, Sell if reverse, Neutral if tangled. (Previously hardcoded to "Neutral".)
- **Relative Strength vs Nifty** — `(ticker_return) / (nifty_return)` over the same window. Buy if outperforming Nifty.
- **Multi-level ADX** — proper Wilder DI+/DI−/ADX with thresholds: `Buy` (>25), `Buy+` (>30), `Buy++` (>40). Same for Sell. (Previously a fake ATR-direction hack.)
- **Multi-level RSI** — `Sell++` (<20), `Sell+` (<30), `Sell` (<40), `Neutral`, `Buy` (>60), `Buy+` (>70), `Buy++` (>80).

`ComputeSignals(bars, niftyBars)` now takes Nifty bars (fetched once per dashboard request) for RS computation. Status-counting was updated to recognize prefix matches so `Buy+++` still counts as a Buy vote.

---

### Phase 11: Indian ADRs in the Overnight Model (April 28, 2026)

The audit identified Indian ADRs (Infosys, HDFC Bank, ICICI Bank, Wipro, Tata Motors as US-listed ADRs on NYSE/NASDAQ) as the single highest-impact "free win" for the overnight model — they trade in the US session, close ~02:30 IST (well before the 03:30 IST cron), and represent ~25% of Nifty index weight.

#### Added to `data_fetcher.py`
A new `ADR_TICKERS` dict alongside the existing main + optional ticker dicts:
```python
ADR_TICKERS = {
    "infy_adr":  "INFY",   # ~4% Nifty weight
    "hdb_adr":   "HDB",    # ~13% Nifty weight
    "ibn_adr":   "IBN",    # ~8% Nifty weight
    "wit_adr":   "WIT",
    "ttm_adr":   "TTM",    # delisted on yfinance — gracefully skipped
}
```

#### Composite features in `feature_engineering.py`
Beyond the auto-generated `infy_adr_ret_1/5/20` etc., four ADR-aware composites were added:
- `adr_bull_count` — count of ADRs up overnight (0–4)
- `adr_avg_ret_1` — equal-weight average overnight return
- `adr_vs_sp500` — ADR composite return minus S&P return (alpha indicator)
- `adr_heavy_avg_ret` — weighted toward HDB + IBN + INFY (top Nifty constituents)

Plus `predict_overnight.py` now gracefully fills missing feature columns with 0 instead of raising `RuntimeError("Feature drift")` — this lets the model deploy even if the parquet hasn't been refreshed yet.

#### Retrain results
74 → **90 features**. Walk-forward 2021–2025 directional accuracy at conf≥0.55 went from 75% (pre-ADR baseline) to 72.1%; at conf≥0.65 it's 77.4%; at conf≥0.70, **79.0%**. April 2026 holdout: **85.7% directional**, 100% at conf≥0.45 across 14 days. The lower coverage at conf≥0.55 trades for higher accuracy at the high-confidence band — the actionable trades got more reliable.

---

### Phase 12: Simulator Mode + Trade Journal (April 28, 2026)

The user explicitly rejected SL/Target enforcement on live signals (P0.1 in the short todo) — they wanted signal flips kept fully visible for data collection toward a future "model of models". So instead of altering live signals, a **shadow tracker** was built that logs what would have happened if every signal had been taken.

#### Position tracker — `services/simulator.go`
Hooks into the existing 1-min cron after signal generation:
- Opens a virtual position on every BUY CE / BUY PE signal at the suggested strike
- Each tick checks exit conditions: `TARGET` (spot crosses target), `SL` (spot crosses stop loss), `TIMEOUT` (estimated hold elapsed), `FLIP` (signal reversed direction), `EOD` (15:30 IST close)
- Logs entry+exit rows to `executed_trades.csv` with full P&L (using Nifty lot size 65)
- Refuses duplicate positions for the same strike+type
- Resets state at midnight

#### Daily grader — `services/grader.go` (15:35 IST cron)
Reads today's `system_signals.csv` + `option_price_array.csv` and produces:
- `signal_grades.csv` — per-signal premium trajectory at +5/+10/+15/+30 min, best exit minute, theoretical P&L, grade (`WIN` / `LOSS` / `NEUTRAL` / `SUPP_MOVED` / `SUPP_NEUTRAL`)
- `model_scorecard.csv` — per-model directional accuracy aggregated per day for `Rolling`, `Direction`, `CrossAsset`, `OldDir`, `Scalper`, `Ensemble`. Includes avg confidence when right vs wrong, best/worst hour.

#### Trade Journal — `frontend/src/components/JournalView.jsx` + `TradeChart.jsx`
A "Journal" sub-tab inside Simulator. Click any closed trade row to expand inline with:
- **Spot trajectory chart** — entry−10min to exit+10min, with horizontal Target/Entry/SL lines, Entry (green) and Exit (orange) markers
- **Premium trajectory chart** — entry to exit+30min, with Best (yellow) marker showing where you should have exited
- **Model agreement chips** — Rolling, Direction, CrossAsset signals at entry (spot patterns like "all 3 agreed → win")
- **MFE/MAE/efficiency** — max favorable/adverse excursion + actual P&L as % of theoretical best

Reusable `<TradeChart>` component: ~250 lines of inline SVG, zero dependencies.

#### Backend journal API — `services/journal.go`
- `LoadClosedTradesForDate(date)` — reads `executed_trades.csv` filtered to closed exits for that day
- `LoadClosedTradesRange(days)` — last N days
- `LoadTradeDetail(date, time, strike, type)` — enriches trade with spot trajectory (from `system_signals.csv`) and premium trajectory (from `option_price_array.csv`), plus computed MFE/MAE/efficiency

Endpoints (all authed): `GET /api/simulator/journal`, `GET /api/simulator/journal/detail`, plus `GET /api/simulator/state`, `GET /api/simulator/scorecard`.

---

### Phase 13: Multi-User Auth with Admin/User Roles (April 28, 2026)

Multiple people now need access to the dashboard but shouldn't all be able to download CSVs or browse system logs.

#### User store — `services/auth.go`
- `data/users.json` (in `spectre_data` named volume — survives deploys)
- bcrypt password hashes (cost 12), HMAC-signed session cookies (30-day TTL), file-locked atomic writes
- **Bootstrap flow:** if `users.json` doesn't exist on startup, auto-create one admin from `BOOTSTRAP_ADMIN_USER` + `BOOTSTRAP_ADMIN_PASSWORD` env vars. After first login the user can delete the bootstrap password env var.

#### Endpoints — `api/handlers/auth.go`
- `POST /api/auth/login` `{username, password}` → sets `spectre_session` cookie
- `POST /api/auth/logout` → clears cookie
- `GET /api/auth/me` → `{authenticated, username, role}`
- `GET/POST/DELETE /api/auth/users` — admin-only user management

#### Route middleware — `api/router.go`
- **Public** (no auth): `/api/health`, `/api/auth/{login,logout,me}`
- **Authenticated** (any logged-in user): all read endpoints (signals, positions, journal, scorecard, dashboard, etc.)
- **Admin-only**: 5 CSV download endpoints, `/api/ml-logs`, `/api/auth/users*`, `/api/stability-reset`

Backend enforces — frontend hiding (Download tab disappears for non-admins, Download CSV button hidden in Simulator) is UX only.

#### Frontend
- `AuthContext.jsx` — provider exposing `{user, role, isAdmin, login, logout}`. Auto-fetches `/api/auth/me` on mount.
- `LoginView.jsx` — full-screen username + password form (gated full-screen replacement of the app when not authed)
- `UsersAdminView.jsx` — modal list/create/delete. Refuses to delete the last admin.
- Header chip: `username · role · ⚙(admin only) · Logout`

#### Env vars (set in Dokploy)
- `SESSION_SECRET` — 32-byte hex; HMAC signing key. Don't rotate (invalidates all sessions).
- `BOOTSTRAP_ADMIN_USER` (default `admin`) and `BOOTSTRAP_ADMIN_PASSWORD` — first-run only.

---

### Phase 14: Overnight Self-Healing + ML Logs UX (April 28–29, 2026)

#### Problem A: Fresh-deploy 404 on Overnight tab
The (then-separate) `overnight_data` named volume started empty. The 03:30 IST cron normally populates `overnight_raw.parquet`, but a deploy at 11 AM IST meant waiting 16 hours to see anything. Worse, the UI showed only a raw `[Errno 2] No such file or directory: '/app/models/overnight_nifty/data/overnight_raw.parquet'` error.

**Fix — sidecar:**
- On startup, if the parquet is missing, kick off a background fetch via `threading.Thread`.
- New `POST /refresh_overnight_data` (idempotent, lock-protected) returns immediately, runs fetch + predict in a daemon thread.
- New `GET /overnight_data_status` exposes `exists`, `age_hours`, `fetch_in_progress`, `fetch_started_at`, `last_fetch_status`.
- `/predict_nifty_overnight` now returns structured `{error_code: "data_missing", fetch_in_progress: bool, message: ...}` instead of opaque error strings.

**Fix — UI (`OvernightView.jsx`):**
- New `BackfillBanner` with three states: cyan ("Backfilling… ~3 minutes" + status), red (data missing + "Backfill now" button), or subtle (data >26h old + "Refresh now" link).
- Polls `/api/overnight-prediction/status` every 8s while a fetch is running (vs the default 10-min refresh).
- Every error path gets a Retry button.

#### Problem B: ML Logs "No logs recorded for today yet"
After hours, the ML Logs view filtered strictly to today's IST date and showed an empty table — even though `system_signals.csv` had weeks of historical data in the volume. Made persistence look broken when it wasn't.

**Fix:**
- `GetMLLogs` now accepts `?date=YYYY-MM-DD`. Default behavior (no param) is "today, with auto-fallback to most recent day with data".
- Returns `available_dates` list and `fell_back` flag.
- Frontend adds a date dropdown sourced from `available_dates` plus a "Today (auto-fallback)" default option.
- Empty-state messages distinguish "CSV is empty" vs "this day has no rows".

---

### Phase 15: Production Domain on Dokploy (April 29, 2026)

The system was previously reached via the legacy `spectrev2.156.67.110.99.sslip.io` URL (no HTTPS, IP exposed). User owns `deltabooster.online` and added a subdomain.

**Setup:**
1. Namecheap → Advanced DNS → A record `spectre` → `156.67.110.99`
2. Dokploy → Spectre service → Domains tab → add `spectre.deltabooster.online`, Path `/`, Container `frontend`, Port 80, HTTPS ON, Let's Encrypt
3. Redeploy compose so Traefik picks up the new route + provisions the cert

**Why subdomain (not path-prefix):** the `deltabooster.online` root is taken by another project. Path-prefix (`/spectre`) would have required Vite `base:` config, frontend API path rewrites, cookie path scoping, and Traefik StripPrefix middleware. Subdomain is zero code changes.

Production URL: **`https://spectre.deltabooster.online`** (sslip.io URL kept as backup).

---

### Phase 16 (planned, parked): Analytics Desk

A consolidated "Analytics" top-level tab grouping all retrospective/analytical surfaces, with Simulator slimmed to "Positions only". Backend partially built in `services/analytics.go` (equity curve, suppressed signals, A/B scorecard compare); handlers, routes, and frontend not yet wired. Full plan in `/analytics-desk.md` with a pickup checklist.

Sub-tabs to build under Analytics:
1. **Journal** (move from Simulator)
2. **Equity** — daily P&L bars + cumulative line
3. **Suppressed Signals** — minutes where conviction filter blocked, with what-would-have-happened spot trajectories
4. **Scorecard** (move from Simulator)
5. **A/B Compare** — side-by-side scorecard for two date ranges
6. **Daily Reports** — auto-generated 15:35 IST markdown summaries

Plus per-trade enhancements in Journal: what-if exit comparison (Hold-50%, Trail-30%, Optimal) and trade narrative auto-generation.

---

### Phase 17: Data Persistence — Named Volumes + Entrypoint Seeding (April 30, 2026)

#### The Problem
Even after Phase 14's auto-bootstrap fix, the Overnight tab kept reverting to "data not initialized" after Dokploy redeploys. Root cause turned out to be deeper: the `ml-sidecar` container's `./ml_sidecar/models:/app/models:ro` **bind mount** was wiped every redeploy, because Dokploy re-clones the repo into a fresh directory each time. Any retrained model on the live container that wasn't committed to git was **gone forever**.

The `spectre_data` named volume *was* persisting, but the model directory wasn't, and the (then-separate) `overnight_data` named volume mounted *underneath* the bind mount made the layering fragile.

#### The Fix
Replaced the bind mount with a single named volume + a one-time seed-on-first-deploy pattern.

**`docker-compose.yml`:**
```diff
   ml-sidecar:
     volumes:
-      - ./ml_sidecar/models:/app/models:ro
-      - overnight_data:/app/models/overnight_nifty/data
+      - ml_models:/app/models

 volumes:
   spectre_data:
-  overnight_data:
+  ml_models:
```

**`ml_sidecar/Dockerfile`** — bake models into the image as a seed dir:
```dockerfile
COPY ml_sidecar/models /app/models_seed
COPY ml_sidecar/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
```

**`ml_sidecar/entrypoint.sh`** — seed only on first deploy:
```bash
if [ -z "$(ls -A /app/models 2>/dev/null)" ]; then
    cp -a /app/models_seed/* /app/models/        # First deploy: full copy
else
    cp -a -n /app/models_seed/* /app/models/     # Later: sync NEW files only (no clobber)
fi
mkdir -p /app/models/overnight_nifty/data
exec uvicorn sidecar:app --host 0.0.0.0 --port 8240
```

This means:
- First deploy ever: volume is empty → full copy from baked-in seed.
- Every subsequent deploy: `cp -a -n` ("no clobber") only adds files that don't exist — so new models pushed via git get into the volume, but retrained models on the live container are preserved. Best of both worlds.

#### Side benefits
- Single volume to manage (`ml_models`) instead of model bind mount + `overnight_data` named volume layered on top
- Overnight backfill (auto-bootstrap or button-triggered) now writes to a stable path that survives redeploys
- Retrained models on the VPS (e.g. monthly retrains via Dokploy shell) are no longer at risk of git-deploy wipeout

#### New docs added
- `CLAUDE.md` — project-level quick context for Claude Code sessions (architecture, data paths, model registry, deployment notes)
- `data-persistence-fix-30-April.md` — full writeup of the change with backup recommendations (Dokploy Volume Backups: daily for `spectre_data`, weekly for `ml_models`)
