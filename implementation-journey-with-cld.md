# Spectre v1.2 - Implementation Journey with Claude

## Session: Bug Fixes & Feature Implementation (April 10, 2026)

---

## 1. Initial Issue Discovery

User shared a screenshot of Spectre v1.2 showing:
- All zeros (0.0% probabilities, 0% confidence, "NO TRADE")
- "Offline" status indicator
- Equity Momentum (0%) and Advance % (0%) with red X badges

Claude explored the repo and identified **8 issues** across the Go backend, Python ML sidecar, and React frontend.

---

## 2. Issues Found (Severity Ranked)

### CRITICAL
1. **"Offline" status always shows** — `health.go` returns `"status": "ok"` but `DataHealthWidget.jsx` checks for `"ONLINE"`. Never matches.
2. **Equity fields declared but never populated** — `EquityConfirms`, `EquityReturn`, `EquityAdvPct` exist in `models/types.go` but `GenerateTradeSignal()` in `trade_signals.go` never assigns values.

### HIGH
3. **Hardcoded model accuracy** — `sidecar.py:262` has `"model_accuracy": 47.56` as a static placeholder.
4. **Architecture doc has wrong port** — `SPECTRE_ARCHITECTURE.md` says `:8001` but actual code connects to `:8240`.

### MEDIUM
5. **Invalid Go time format** — `trade_signals.go:139` uses `"03:04 PM"` format.
6. **ML sidecar feature validation** — Cross-asset predictions could fail silently.

### LOW
7. **Insufficient bars validation** — Yahoo Finance data could be corrupt.
8. **Port documentation mismatch** in sidecar.py run comment.

---

## 3. Fix #1 — Offline Status, Equity Fields, Port Docs

**Commit: `a56a2bf`**

### Changes:
- **`api/handlers/health.go`**: Changed return value from `"ok"` to `"ONLINE"` to match frontend check
- **`services/trade_signals.go`**: Added equity computation logic:
  - `EquityReturn` — current bar's close vs open as %
  - `EquityAdvPct` — % of last 20 bars where close > open
  - `EquityConfirms` — true if equity direction matches ML prediction
- **`ml_sidecar/sidecar.py`**: Fixed run comment port 8001 -> 8240
- **`services/ml_sidecar.go`**: Fixed code comment port 8001 -> 8240
- **`SPECTRE_ARCHITECTURE.md`**: Fixed architecture doc port 8001 -> 8240

### Result:
- Online status now shows green with "Online (0 streams)" ✓
- Advance % now shows 60% with green checkmark ✓
- Probabilities still 0% — ML sidecar connection issue

---

## 4. Fix #2 — ML Sidecar Volume Mount Path

**Commit: `c15a3c8`**

### Root Cause:
`docker-compose.yml` mounted models at `/models` but `sidecar.py` looks for them at `/app/models` (because `__file__` = `/app/sidecar.py` and `ML_DIR = os.path.join(os.path.dirname(__file__), "models")`).

### Change:
- **`docker-compose.yml`**: `./ml_sidecar/models:/models:ro` -> `./ml_sidecar/models:/app/models:ro`

### Result:
Models now visible to sidecar container, but still showing zeros...

---

## 5. Fix #3 — Sidecar Blocking Event Loop

**Commit: `c0ea54a`**

### Root Cause:
`_load()` was called **inside the `/predict` endpoint on every request**, loading 16MB of `.pkl` files synchronously inside an async function. This blocked the event loop and hit Go's 8-second HTTP timeout.

### Changes:
- **`ml_sidecar/sidecar.py`**: Moved `_load()` to `@app.on_event("startup")` so models load once at boot
- **`services/ml_sidecar.go`**: Added error check for sidecar error JSON — previously Go silently parsed error responses as zero-value structs

---

## 6. Fix #4 — Institutional Outlook Endpoint + Nginx DNS

**Commit: `ed19c12`**

### Root Cause:
- Frontend had an "Institutional Outlook" tab hitting `/api/institutional-outlook` but **no such route existed in Go**
- Nginx cached stale container IPs after Dokploy redeploys

### Changes:
- **New file `services/institutional.go`** — Full implementation of 9 analysis modules:
  1. Smart Money (CMF + OBV divergence)
  2. Gamma Exposure (PCR + GEX + max pain from OI chain)
  3. Intermarket (India VIX, S&P, Gold, Oil)
  4. Market Breadth (advance/decline from top Nifty contributors)
  5. Sector Rotation (cyclical vs defensive)
  6. Volatility Regime (VIX zones + ATR)
  7. Momentum (multi-RSI cascade, MACD, EMA stack)
  8. Institutional Flows (large-cap vs mid-cap proxy)
  9. Risk Assessment (EMA distance, R:R ratio, OI levels)
  - Composite scoring with verdict, confidence, and agreement ratio
- **New file `api/handlers/institutional.go`** — Handler for the endpoint
- **`api/router.go`** — Wired `/api/institutional-outlook` route
- **`frontend/nginx.conf`** — Added Docker DNS resolver (`127.0.0.11`) for dynamic IP resolution

---

## 7. Fix #5 — Nginx URI Proxying + Sidecar Hardening

**Commit: `1f90357`**

### Root Cause:
Previous nginx fix used a variable for `proxy_pass` (`set $backend ...`), but when nginx uses a variable, it **stops appending the request URI**. So every API request hit `http://spectre:8239/` (root) instead of the correct path — Go returned 404 for everything. This caused "Failed to fetch trade signals".

### Changes:
- **`frontend/nginx.conf`**: Added `$request_uri` to proxy_pass: `proxy_pass $backend$request_uri;`
- **`ml_sidecar/sidecar.py`**:
  - Added `_clean_bars()` function to filter `None`/NaN values from Yahoo Finance data
  - Used metadata accuracy instead of hardcoded 47.56%
  - Added specific error messages for each failure point
  - Logged cross-asset errors with traceback instead of silent `pass`

---

## 8. Fix #6 — Dual Model Ensemble + IST Timezone (In Progress)

### Issues Identified:
1. **Missing direction model**: `_get_model_paths()` was defined but never called — only the rolling model loaded. The direction model (`nifty_direction_model_5m.pkl`) was never used.
2. **UTC timezone in Docker**: `time.Now()` gives UTC in container, so "Valid until" was 5.5 hours behind IST.
3. **Missing time features**: `feat_hour` and `feat_minutes_since_open` in sidecar computed from UTC, not IST — feeding wrong time features to model.

### Changes (auto-applied by linter/user):
- **`services/trade_signals.go`**:
  - Uses `time.LoadLocation("Asia/Kolkata")` for Valid Until calculation
  - Caps Valid Until to market close (3:30 PM IST)
  - Minimum hold duration of 5 minutes
  - Bounds-checks prediction indices
  - Added `buildModelsBreakdown()` for per-model signal breakdown
  - Changed error returns from empty structs to proper `fmt.Errorf` with wrapping
  - OI support/resistance uses actual max OI strike instead of arbitrary offset

- **`ml_sidecar/sidecar.py`**:
  - Loads **3 models**: rolling (stable), direction_5m (scalp), old direction_1h (trend bias)
  - Ensemble: averages rolling + direction probabilities
  - Returns per-model breakdown in response (`models` field)
  - Uses IST timezone for time features (`zoneinfo.ZoneInfo("Asia/Kolkata")`)
  - Added `aiohttp.ClientTimeout` for Yahoo Finance requests

- **`docker-compose.yml`**:
  - Added `TZ=Asia/Kolkata` environment variable to both `spectre` and `ml-sidecar` containers
  - Added `RESET_KEY` env var for stability reset endpoint security

- **`api/router.go`**:
  - Added `guardReset` middleware protecting `/stability-reset` with `X-Reset-Key` header
  - Added `net/http` and `os` imports

- **`models/types.go`** (implied):
  - Added `ModelsBreakdown`, `ModelOutput` structs
  - Added `Models` field to `TradeSignal`

- **`services/ml_sidecar.go`** (implied):
  - Added `ModelOutput`, `ModelsInfo` structs to parse sidecar's new `models` field

---

## Architecture Summary

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   React Frontend │────>│   Nginx (port 80) │────>│  Go Backend      │
│   (Vite + JSX)   │     │   Docker DNS Res. │     │  (Gin, port 8239)│
└──────────────────┘     └──────────────────┘     └────────┬─────────┘
                                                           │
                                                           │ HTTP /predict
                                                           v
                                                  ┌──────────────────┐
                                                  │  Python Sidecar  │
                                                  │  (FastAPI, 8240) │
                                                  │                  │
                                                  │  3 XGBoost Models│
                                                  │  - Rolling (5m)  │
                                                  │  - Direction (5m)│
                                                  │  - Cross-Asset   │
                                                  │    (BankNifty)   │
                                                  │                  │
                                                  │  + Old 1h model  │
                                                  └──────────────────┘
```

## Key Files Modified
- `api/handlers/health.go` — Health status response
- `api/handlers/institutional.go` — **NEW** Institutional outlook handler
- `api/router.go` — Route wiring + reset guard
- `docker-compose.yml` — Volume mount, timezone, env vars
- `frontend/nginx.conf` — DNS resolver + URI proxying
- `ml_sidecar/sidecar.py` — Model loading, prediction pipeline, error handling
- `models/types.go` — Struct definitions
- `services/institutional.go` — **NEW** 9-module institutional analysis
- `services/ml_sidecar.go` — Go-side ML client + error surfacing
- `services/trade_signals.go` — Signal generation, equity fields, IST timezone
- `SPECTRE_ARCHITECTURE.md` — Port documentation fix

## Commits
1. `a56a2bf` — Fix offline status, zero equity fields, and port doc mismatches
2. `c15a3c8` — Fix ml-sidecar volume mount path: /models -> /app/models
3. `c0ea54a` — Fix sidecar blocking event loop and silent error swallowing
4. `ed19c12` — Add /api/institutional-outlook endpoint and fix nginx DNS caching
5. `1f90357` — Fix nginx URI proxying and harden ML sidecar prediction pipeline
6. (Pending) — Dual model ensemble + IST timezone + models breakdown
