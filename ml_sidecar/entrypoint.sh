#!/bin/bash
set -e

# ── Seed/sync models into the named volume ─────────────────────────────────
# /app/models  → Docker named volume (ml_models), persists across redeploys.
# /app/models_seed → Baked into the image from ml_sidecar/models/ at build time.
#
# Sync policy:
#   • Code + model artifacts (.py/.pkl/.json/.keras): the REPO is the source
#     of truth — copied from seed whenever content differs, so retrained
#     models shipped via git actually deploy.
#   • overnight_nifty/data/: the VOLUME is the source of truth — runtime data
#     collected/refreshed on the VPS is never overwritten; only seeded when
#     missing (fresh volume).

if [ -z "$(ls -A /app/models 2>/dev/null)" ]; then
    echo "[entrypoint] First deploy — seeding /app/models from image..."
    cp -a /app/models_seed/* /app/models/
    echo "[entrypoint] Seed complete ($(du -sh /app/models | cut -f1))."
else
    echo "[entrypoint] Syncing model artifacts from image seed..."
    synced=0
    while IFS= read -r -d '' src; do
        rel="${src#/app/models_seed/}"
        dst="/app/models/$rel"
        case "$rel" in
            overnight_nifty/data/*)
                # Volume-owned runtime data — never overwrite.
                [ -e "$dst" ] && continue
                ;;
        esac
        if [ ! -e "$dst" ] || ! cmp -s "$src" "$dst"; then
            mkdir -p "$(dirname "$dst")"
            cp -a "$src" "$dst"
            echo "[entrypoint]   updated: $rel"
            synced=$((synced+1))
        fi
    done < <(find /app/models_seed -type f -print0)
    echo "[entrypoint] Sync done ($synced file(s) updated)."
fi

# Ensure overnight data subdir exists on the volume.
mkdir -p /app/models/overnight_nifty/data

exec uvicorn sidecar:app --host 0.0.0.0 --port 8240
