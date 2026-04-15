# Spectre Go

A Go rewrite of the Spectre trading dashboard backend — same API surface,
~10x lower memory, ~5x faster response times, single binary deploy.

## Architecture

```
┌─────────────────────────────────────────┐
│  React Frontend (Vite, port 5173)       │
│  ├─ Cockpit View (default)              │
│  ├─ Trade Signals, Market Direction     │
│  ├─ OI Trending, Multitimeframe         │
│  ├─ Heatmap, Institutional, News        │
│  └─ ML Logs                             │
└──────────────┬──────────────────────────┘
               │ HTTP
┌──────────────▼──────────────────────────┐
│  Go Server (port 8239)                  │
│  ├─ /api/dashboard      (indicators)    │
│  ├─ /api/market-direction               │
│  ├─ /api/oi-chain                       │
│  ├─ /api/trade-signals                  │
│  ├─ /api/institutional-outlook          │
│  ├─ /api/stability-state                │
│  ├─ /api/stability-reset                │
│  └─ /api/ml-logs                        │
└──────────────┬──────────────────────────┘
               │ HTTP (localhost)
┌──────────────▼──────────────────────────┐
│  Python ML Sidecar (port 8240)          │
│  ├─ GET /predict  → signal + probs      │
│  ├─ GET /ohlcv    → Yahoo Finance proxy │
│  └─ GET /oi       → NSE OI chain proxy  │
│                                         │
│  Models (XGBoost + LSTM):               │
│  ├─ nifty_multitf_model-Rtr14April.pkl  │
│  ├─ nifty_lstm_model-Rtr14April.keras   │
│  ├─ nifty_rolling_model-Rtr14April.pkl  │
│  └─ nifty_cross_asset_model-Rtr14April.pkl
└─────────────────────────────────────────┘
               │ External (via sidecar only)
    Yahoo Finance + NSE OI Chain API
```

> **Note:** All external HTTP requests (Yahoo Finance OHLCV, NSE OI chain) are proxied through the Python sidecar. Go's TLS fingerprint is blocked by Akamai/Yahoo on datacenter IPs; Python aiohttp is not.

## Run (development)

```bash
# Terminal 1: ML Sidecar
cd ml_sidecar
pip install -r requirements.txt
uvicorn sidecar:app --port 8240

# Terminal 2: Go server
go run .

# Terminal 3: Frontend (optional, dev mode)
cd frontend && npm run dev
```

## Build & Deploy

```bash
# Single binary
go build -ldflags="-s -w" -o spectre .

# Docker
docker-compose up --build
```

## ML Models

Four XGBoost/LSTM models are loaded by the sidecar. All retrained models use the `-Rtr14April` suffix alongside the originals for safe rollback.

| Model | File | Description |
|---|---|---|
| Multi-TF | `nifty_multitf_model-Rtr14April.pkl` | 1m/5m/15m timeframe ensemble |
| LSTM | `nifty_lstm_model-Rtr14April.keras` | Sequence-based pattern recognition |
| Rolling Master | `nifty_rolling_model-Rtr14April.pkl` | Conservative 1m rolling windows |
| Cross-Asset | `nifty_cross_asset_model-Rtr14April.pkl` | Aggressive BankNifty divergence hunter |

**Features (39 total):** 31 base TA indicators + 4 momentum features (`feat_consec_up`, `feat_consec_down`, `feat_session_position`, `feat_momentum_divergence`) + 4 India VIX features (`feat_vix_level`, `feat_vix_change`, `feat_vix_vs_avg`, `feat_vix_regime`).

## Retrain Models

```bash
cd ml_sidecar/models

# 1. Multi-TF + LSTM (1m, 5m, 15m)
python train_multitf.py

# 2. Rolling Master (1m rolling windows, RandomizedSearchCV)
python train_rolling_master.py

# 3. Cross-Asset (BankNifty + Nifty divergence)
python train_cross_asset.py
```

Training data path: `/Users/manasingle/Edge/Market Dataset since 2015/`
Required files: `NIFTY 50_minute.csv`, `NIFTY BANK_minute.csv`, `INDIA VIX_minute.csv`

## vs Python FastAPI

| Metric          | Python FastAPI | Spectre Go   |
|-----------------|---------------|--------------|
| Memory (idle)   | ~250MB        | ~20MB        |
| Response time   | ~40-80ms      | ~5-15ms      |
| Startup time    | ~4s           | ~50ms        |
| Binary size     | ~600MB (venv) | ~12MB        |
| Concurrency     | GIL-limited   | goroutines   |
| ML inference    | In-process    | Sidecar HTTP |
