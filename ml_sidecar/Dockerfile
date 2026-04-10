FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi uvicorn aiohttp numpy pandas \
    scikit-learn xgboost joblib ta tensorflow
COPY ml_sidecar/sidecar.py .
EXPOSE 8240
CMD ["uvicorn", "sidecar:app", "--host", "0.0.0.0", "--port", "8240"]
