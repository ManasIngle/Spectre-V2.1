# Spectre Go — Project Context for Claude Code

## Architecture Overview

Spectre is a **Nifty options trading signal system** deployed on a VPS via **Dokploy** (Docker Compose).
It consists of three services:

| Service | Language | Port | Role |
|---|---|---|---|
| `spectre` | Go (Gin) | 8239 | Backend API + cron signal engine |
| `ml-sidecar` | Python (FastAPI) | 8240 | ML inference (XGBoost, LSTM, Keras) |
| `frontend` | HTML/JS | — | Dashboard UI (served via Nginx) |

## Key Data Paths

### Go Backend (`spectre` service)
- All persistent data lives at `SPECTRE_DATA_DIR=/app/data` (Docker named volume `spectre_data`).
- `services/paths.go` — `DataDir()` / `DataPath()` resolve file locations.
- Files: `system_signals.csv`, `executed_trades.csv`, `signal_grades.csv`, `model_scorecard.csv`, `option_price_array.csv`, `users.json`

### ML Sidecar (`ml-sidecar` service)
- Model files (`.pkl`, `.keras`, `.json`) live at `/app/models` (Docker named volume `ml_models`).
- On first deploy, `entrypoint.sh` seeds the volume from `/app/models_seed` (baked into the image).
- On subsequent deploys, only NEW files are synced (existing models are preserved).
- Overnight data lives at `/app/models/overnight_nifty/data/`.

## ML Models (6 total)

| # | Model | File | Type | Purpose |
|---|---|---|---|---|
| 1 | Rolling | `nifty_rolling_model.pkl` | XGBoost | Stable anti-whipsaw signal |
| 2 | Direction | `nifty_direction_model.pkl` | XGBoost | 5m scalp trigger |
| 3 | CrossAsset | `nifty_cross_asset_model.pkl` | XGBoost | BankNifty correlation |
| 4 | OldDirection | `nifty_direction_model_5m.pkl` | XGBoost | 1h trend bias |
| 5 | Scalper | `nifty_scalper_lstm.keras` | LSTM | 3-minute horizon |
| 6 | Overnight | `overnight_nifty/` directory | Stacked XGB+LSTM | Next-day close prediction |

### Trade Signal Flow
1. **Cron** (`services/cron.go`) fires every 1 minute, 09:00–15:30 IST.
2. Calls `GenerateTradeSignal()` → fetches `/predict` from the Python sidecar.
3. The sidecar's `/predict` endpoint **ensembles Rolling + Direction** models (probability average → argmax).
4. Go applies a **>35% confidence threshold** → BUY CE / BUY PE / NO TRADE.
5. `SimOnSignal()` opens a virtual position in the simulator; `SimTick()` checks target/SL/timeout.
6. Individual model signals (Rolling, Direction, CrossAsset) are logged alongside for comparison but **do NOT influence the trade decision** — only the ensemble does.

## Deployment (Dokploy)

- **Platform**: Dokploy on VPS, Docker Compose mode.
- **Volumes**: Named volumes (`spectre_data`, `ml_models`) persist across redeploys.
- **Important**: The `ml-sidecar` Dockerfile bakes models into `/app/models_seed`, and `entrypoint.sh` seeds the named volume only on first deploy (won't overwrite retrained models).
- **Backup strategy**: Dokploy Volume Backups (daily for `spectre_data`, weekly for `ml_models`). Requires S3 destination setup.
- **Manual backup**: Download CSVs from Spectre UI → Download tab.

## Common Tasks

- **Retrain models**: Run `train_rolling_master.py`, `train_multitf.py`, `train_cross_asset.py`, or `train_scalper_lstm.py` in `ml_sidecar/models/`.
- **Backtest**: `python3 backtest/backtest.py`
- **Local dev**: `go run .` (Go backend) + `uvicorn sidecar:app --port 8240` (Python sidecar)
- **Build**: `go build -o spectre .`

## Recent Changes (30 April 2026)

- **Data Persistence Fix**: Replaced bind mount for ML models with named volume + entrypoint seeding to survive Dokploy redeploys. See `data-persistence-fix-30-April.md` for details.
