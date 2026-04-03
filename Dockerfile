# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.13-slim AS base

# System deps (needed for some pandas/numpy wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── App stage ─────────────────────────────────────────────────────────────────
COPY . .

# Streamlit config — disable telemetry, set port, enable CORS for Azure
RUN mkdir -p /root/.streamlit && cat > /root/.streamlit/config.toml <<'EOF'
[server]
port = 8501
headless = true
enableCORS = false
enableXsrfProtection = false

[browser]
gatherUsageStats = false

[theme]
base = "light"
EOF

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0"]
