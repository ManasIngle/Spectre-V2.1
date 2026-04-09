# Spectre Go

A Go rewrite of the Spectre trading dashboard backend — same API surface,
~10x lower memory, ~5x faster response times, single binary deploy.

## Architecture

```
┌─────────────────────────────────────────┐
│  Go Server (port 8000)                  │
│  ├─ /api/dashboard      (indicators)    │
│  ├─ /api/market-direction               │
│  ├─ /api/oi-chain                       │
│  ├─ /api/trade-signals                  │
│  ├─ /api/stability-state                │
│  └─ /api/stability-reset                │
└──────────────┬──────────────────────────┘
               │ HTTP (localhost)
┌──────────────▼──────────────────────────┐
│  Python ML Sidecar (port 8001)          │
│  ├─ Loads XGBoost .pkl + LSTM .keras    │
│  ├─ GET /predict → {probs, ensemble}    │
│  └─ Stays in memory between calls       │
└─────────────────────────────────────────┘
```

## Run (development)

```bash
# Terminal 1: ML Sidecar
cd ml_sidecar && pip install -r requirements.txt
uvicorn sidecar:app --port 8001

# Terminal 2: Go server
export PATH=$PATH:/opt/homebrew/bin
go run .
```

## Build & Deploy

```bash
# Single binary
go build -ldflags="-s -w" -o spectre .

# Docker
docker-compose up --build
```

## vs Python FastAPI

| Metric          | Python FastAPI | Spectre Go   |
|-----------------|---------------|--------------|
| Memory (idle)   | ~250MB        | ~20MB        |
| Response time   | ~40-80ms      | ~5-15ms      |
| Startup time    | ~4s           | ~50ms        |
| Binary size     | ~600MB (venv) | ~12MB        |
| Concurrency     | GIL-limited   | goroutines   |
| ML inference    | In-process    | Sidecar HTTP |
