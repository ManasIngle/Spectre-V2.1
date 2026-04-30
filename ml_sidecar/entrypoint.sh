#!/bin/bash
set -e

# ── Seed models into the named volume on first deploy ──────────────────────
# /app/models  → Docker named volume (ml_models), persists across redeploys.
# /app/models_seed → Baked into the image from ml_sidecar/models/ at build time.
#
# First deploy:  volume is empty → full copy from seed.
# Later deploys: volume already has data → only copy NEW files (--no-clobber).

if [ -z "$(ls -A /app/models 2>/dev/null)" ]; then
    echo "[entrypoint] First deploy — seeding /app/models from image..."
    cp -a /app/models_seed/* /app/models/
    echo "[entrypoint] Seed complete ($(du -sh /app/models | cut -f1))."
else
    echo "[entrypoint] /app/models already populated — skipping full seed."
    # Sync any NEW files added to the repo since last deploy (won't overwrite).
    cp -a -n /app/models_seed/* /app/models/ 2>/dev/null || true
    echo "[entrypoint] New-file sync done."
fi

# Ensure overnight data subdir exists on the volume.
mkdir -p /app/models/overnight_nifty/data

exec uvicorn sidecar:app --host 0.0.0.0 --port 8240
