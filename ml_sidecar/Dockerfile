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
