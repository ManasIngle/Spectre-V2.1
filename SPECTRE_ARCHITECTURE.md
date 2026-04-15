# SPECTRE QUANTITATIVE TRADING SYSTEM: ARCHITECTURE

## Executive Summary
Spectre is a high-frequency, multi-model quantitative trading system designed exclusively for the Nifty 50 Index Options market. It uses four custom ML engines (XGBoost + LSTM) trained on 10 years of 1-minute data, a compiled Go backend for low-latency routing and state management, a Python sidecar for ML inference and external API proxying, and a React frontend with a Bloomberg-style Cockpit view.

---

## 1. The Machine Learning Engine (Python Sidecar)

The sidecar (`ml_sidecar/sidecar.py`) loads all four models on startup and serves predictions via a FastAPI HTTP server on port 8240.

### A. Rolling Master Model (Conservative)
* **File:** `nifty_rolling_model-Rtr14April.pkl`
* **Training:** `train_rolling_master.py` — RandomizedSearchCV + TimeSeriesSplit on 1m data
* **Window:** True 1-minute ticks stitched into overlapping 5-minute rolling candles (works with 1–5 bars, signals from the first minute of the session)
* **Profile:** Conservative. Excels at staying out of sideways chop. Predicts `SIDEWAYS` aggressively to protect options premium.
* **Edge:** ~47.5% accuracy on 3-class (UP/SIDEWAYS/DOWN) — meaningful alpha over random chance.

### B. Cross-Asset Breakout Model (Aggressive)
* **File:** `nifty_cross_asset_model-Rtr14April.pkl`
* **Training:** `train_cross_asset.py` — BankNifty + Nifty 50 synchronized minute data
* **Extra Features:** `feat_bank_spread` (BankNifty vs Nifty divergence), `feat_bank_volatility` (BankNifty range/close)
* **Profile:** Aggressive class weights — heavily penalizes missing UP/DOWN trends. Overall accuracy is lower (~28–30%) but trend recall (catching real breakouts) exceeds 54%.
* **Edge:** Captures over half of violent intraday momentum moves before they appear on standard charts.

### C. Multi-Timeframe Model
* **File:** `nifty_multitf_model-Rtr14April.pkl`
* **Training:** `train_multitf.py` — parallel training on 1m, 5m, 15m timeframes
* **Profile:** Confluence-based. Signal is strongest when multiple timeframes agree.

### D. LSTM Sequence Model
* **File:** `nifty_lstm_model-Rtr14April.keras`
* **Training:** `train_multitf.py` — LSTM on 60-bar sequences of normalized features
* **Profile:** Pattern recognition on temporal sequences. Complements the tree-based XGBoost models.

### Feature Set (39 Total)

**31 Base Technical Indicators:**
RSI, MACD, MACD Signal, Bollinger Bands (upper/mid/lower), ATR, Stochastic K/D, CCI, Williams %R, EMA (9/21/50), SMA (20), VWAP, OBV, MFI, ADX, Plus/Minus DI, Parabolic SAR, Ichimoku (Tenkan/Kijun/Senkou A/B), ROC, Momentum, Historical Volatility.

**4 Momentum Features (added April 2026):**
| Feature | Description |
|---|---|
| `feat_consec_up` | Consecutive bullish closes — measures momentum streak strength |
| `feat_consec_down` | Consecutive bearish closes — measures downside momentum |
| `feat_session_position` | Normalized intraday time (0.0 at 9:15 → 1.0 at 15:30) |
| `feat_momentum_divergence` | Price momentum minus RSI momentum — detects hidden divergence |

**4 India VIX Features (added April 2026):**
| Feature | Description |
|---|---|
| `feat_vix_level` | Raw VIX value — absolute fear gauge |
| `feat_vix_change` | 5-bar rate of change in VIX |
| `feat_vix_vs_avg` | VIX deviation from its 20-bar rolling mean |
| `feat_vix_regime` | Binary flag: 1 if VIX > 20 (high-fear regime) |

VIX is fetched live (`^INDIAVIX` via Yahoo Finance) at prediction time so inference matches training exactly.

### Asymmetric Training Design
All models use asymmetric thresholds and weights based on backtest analysis (BUY PE win rate: 47.9%, BUY CE win rate: 63.1%):

```
Target labeling:   UP threshold = 0.08%,  DOWN threshold = 0.104% (×1.3)
Class weights:     DOWN weight ×= 0.7      (suppresses false bearish signals)
```

### Model Versioning
Retrained models use the `-Rtr14April` suffix. The sidecar loads versioned models with a fallback to originals, enabling zero-risk rollback:
```python
VER = "-Rtr14April"
# nifty_rolling_model-Rtr14April.pkl → fallback: nifty_rolling_model.pkl
```

---

## 2. The Core Backend (Go Microservice)

Go runs on port `8239`. It handles all routing, caching, signal state, and the headless cron loop.

### A. External Data Proxying
All external HTTP calls are proxied through the Python sidecar to avoid Go's TLS fingerprint being blocked by Akamai/Yahoo on datacenter IPs:

| Data Source | Go Service | Sidecar Endpoint |
|---|---|---|
| Yahoo Finance OHLCV | `services/market_data.go` → `fetchOHLCVViaSidecar()` | `GET /ohlcv` |
| NSE OI Chain | `services/oi_data.go` → `fetchOIViaSidecar()` | `GET /oi` |

Go tries the sidecar first and falls back to a direct fetch if the sidecar is unavailable.

### B. The Stability Engine
Go wraps raw ML predictions with hysteresis logic to prevent signal whipsawing:
* **Conviction Rule:** If the ML reverses direction but confidence gap < 8%, Go suppresses the flip and holds the previous signal.
* **Dynamic Hold Time:** Exit time scales by confidence and direction:
  - `BUY PE` (DOWN): 8 min (historically lower win rate — exit fast)
  - `BUY CE` (UP), high confidence (>60%): 10 min
  - `BUY CE`, medium confidence (>45%): 25 min
  - `BUY CE`, low confidence: 15 min

### C. VPS Headless Cron
A native Go goroutine fires every 60 seconds between 09:00–15:30 IST:
1. Bypasses all caches, fetches fresh tick data via sidecar
2. Calls `/predict` on the sidecar for a fresh ML signal
3. Writes full output (signal, confidence, probabilities) to `system_signals.csv`

The bot accumulates data and runs completely without a browser session.

---

## 3. The Frontend (React + Vite)

### Cockpit View (Default)
Bloomberg Terminal-style 3-column layout loaded by default. No scrolling required.

| Column | Content |
|---|---|
| Left | Active Trade Signal (direction, confidence, hold time) + OI Analysis (PCR, Max Pain, support/resistance strikes) |
| Center | Market Direction composite score (0–100 arc gauge) + Multi-timeframe confluence table |
| Right | Institutional Outlook composite + module breakdown bars + intermarket chips (SGX Nifty, DXY, Crude Oil) |

Auto-refreshes every 30 seconds via parallel API calls to `/api/trade-signals`, `/api/market-direction`, `/api/institutional-outlook`.

### Tab Navigation
9 tabs in a horizontal pill nav bar (replaces the previous dropdown):
`Cockpit | Trade Signals | Market Direction | OI Trending | Multitimeframe | Heatmap | Institutional | News | ML Logs`

---

## 4. Data Flow (Full Request Cycle)

```
User opens Cockpit
        │
        ▼
React fires 3 parallel fetch()
  /api/trade-signals
  /api/market-direction
  /api/institutional-outlook
        │
        ▼
Go receives request
  ├─ Checks TTL cache (25s for OHLCV, 60s for signals)
  └─ If stale: calls Python sidecar
              │
              ▼
     Python sidecar /predict
       ├─ Fetches OHLCV via Yahoo Finance (aiohttp — bypasses TLS block)
       ├─ Fetches ^INDIAVIX live
       ├─ Builds rolling 5m window (1–5 bars supported)
       ├─ Extracts 39 features
       └─ Runs 4 models → ensemble → returns JSON
              │
              ▼
Go applies Stability Engine (conviction filter + hold time)
        │
        ▼
React renders Cockpit columns
```
