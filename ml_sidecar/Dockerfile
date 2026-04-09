FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn aiohttp numpy pandas \
    scikit-learn xgboost joblib ta tensorflow
COPY ml_sidecar/sidecar.py .
EXPOSE 8001
CMD ["uvicorn", "sidecar:app", "--host", "0.0.0.0", "--port", "8001"]
