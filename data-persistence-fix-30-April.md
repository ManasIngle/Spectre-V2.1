# Spectre Data Persistence Fix — 30 April 2026

## The Problem

Every redeploy on Dokploy **rebuilds containers from scratch**, which means:
- The `ml-sidecar` container's `./ml_sidecar/models:/app/models:ro` **bind mount** gets wiped because Dokploy re-clones the repo into a fresh directory each time.
- The **named volumes** (`spectre_data`, `overnight_data`) *should* survive — but if Dokploy does a `docker compose down -v` (which removes volumes) or the compose project name changes between deploys, they get nuked too.

### What Gets Lost on Redeploy

| Container | File | Path | Currently Persisted? |
|---|---|---|---|
| `spectre` | `system_signals.csv` | `/app/data/` | ⚠️ Named volume — survives if Dokploy doesn't `down -v` |
| `spectre` | `executed_trades.csv` | `/app/data/` | ⚠️ Same |
| `spectre` | `signal_grades.csv` | `/app/data/` | ⚠️ Same |
| `spectre` | `model_scorecard.csv` | `/app/data/` | ⚠️ Same |
| `spectre` | `option_price_array.csv` | `/app/data/` | ⚠️ Same |
| `spectre` | `users.json` | `/app/data/` | ⚠️ Same |
| `ml-sidecar` | `overnight_raw.parquet` | `/app/models/overnight_nifty/data/` | ⚠️ Named volume |
| `ml-sidecar` | `overnight_predictions.csv` | `/app/models/overnight_nifty/data/` | ⚠️ Named volume |
| `ml-sidecar` | All `.pkl` / `.keras` / `.json` models | `/app/models/` | ❌ **LOST** — bind mount from repo clone |

> **CAUTION:** The trained model files (`.pkl`, `.keras`, metadata `.json`) are mounted as `./ml_sidecar/models:/app/models:ro`. When Dokploy re-clones the repo, the old clone directory is deleted. If a model retrain happened on the live container but wasn't committed to git, **those retrained models are gone forever**.

---

## The Fix: Two-Part Strategy

### Part 1: Ensure Named Volumes Are Truly Persistent

The `docker-compose.yml` already declares `spectre_data` and `overnight_data` as named volumes — these **should** survive across `docker compose up --build`. The issue is likely Dokploy's default behavior.

**Check in Dokploy → Advanced tab:**
1. Ensure the compose command does **NOT** include `-v` flag (which removes volumes)
2. Ensure the "Docker Compose Command" is set to something like: `docker compose up -d --build --remove-orphans` (no `down -v` step)

### Part 2: Move ML Models Into a Named Volume (Critical Fix)

The bind mount `./ml_sidecar/models:/app/models:ro` is the root cause of model loss. Replace it with a named volume + a one-time copy on container start.

---

## Implementation

### 1. Updated `docker-compose.yml`

```diff
 services:
   ml-sidecar:
     volumes:
-      # Trained model artifacts — read-only, shipped with the repo.
-      - ./ml_sidecar/models:/app/models:ro
-      # Overnight model runtime data (predictions log + refreshed parquet).
-      - overnight_data:/app/models/overnight_nifty/data
+      # Named volume for ALL model artifacts + runtime data.
+      # On first deploy the entrypoint seeds from the baked-in /app/models_seed.
+      # On subsequent deploys the volume already has data — seed is skipped.
+      - ml_models:/app/models

 volumes:
   spectre_data:        # system_signals.csv, executed_trades.csv, users.json, etc.
-  overnight_data:      # overnight_predictions.csv, overnight_raw.parquet
+  ml_models:           # ALL ML model files (.pkl, .keras, .json) + overnight data
```

### 2. Updated `ml_sidecar/Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tzdata libgomp1 && rm -rf /var/lib/apt/lists/*
COPY ml_sidecar/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ml_sidecar/sidecar.py .

# Bake model files into the image as a seed directory.
# The entrypoint copies them to the named-volume mount (/app/models)
# ONLY on first deploy — subsequent deploys preserve the volume's data.
COPY ml_sidecar/models /app/models_seed

COPY ml_sidecar/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8240
ENTRYPOINT ["/app/entrypoint.sh"]
```

### 3. New `ml_sidecar/entrypoint.sh`

```bash
#!/bin/bash
set -e

# Seed models into the named volume on first deploy.
# /app/models → Docker named volume (ml_models), persists across redeploys.
# /app/models_seed → Baked into the image from ml_sidecar/models/ at build time.
if [ -z "$(ls -A /app/models 2>/dev/null)" ]; then
    echo "[entrypoint] First deploy — seeding /app/models from image..."
    cp -a /app/models_seed/* /app/models/
    echo "[entrypoint] Seed complete."
else
    echo "[entrypoint] /app/models already populated — skipping full seed."
    cp -a -n /app/models_seed/* /app/models/ 2>/dev/null || true
    echo "[entrypoint] New-file sync done."
fi

mkdir -p /app/models/overnight_nifty/data
exec uvicorn sidecar:app --host 0.0.0.0 --port 8240
```

---

## Dokploy Volume Backup Setup

| Backup Name | Volume | Schedule | Retention |
|---|---|---|---|
| `spectre-data-daily` | `spectre_data` | `0 16 * * 1-5` (4 PM IST, after market) | 30 days |
| `ml-models-weekly` | `ml_models` | `0 18 * * 0` (Sunday 6 PM) | 8 backups |

> **TIP:** The `spectre_data` backup is the most critical — it contains your trade journal, signals, grades, and user auth. Back this up daily after market close.

---

## Summary of Changes

| What | Before | After |
|---|---|---|
| ML model files | Bind mount from repo clone (lost on redeploy) | Named volume `ml_models` + seed-on-first-deploy |
| Overnight data | Separate `overnight_data` volume | Merged into `ml_models` volume (simpler) |
| Signal/trade CSVs | Named volume `spectre_data` (already correct) | Unchanged — just add Dokploy backup schedule |
| Dokploy backups | None configured | Daily for data, weekly for models |
