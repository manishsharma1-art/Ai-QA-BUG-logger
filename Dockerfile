FROM python:3.11-slim

WORKDIR /app

# ─────────────────────────────────────────────
# Build marker — written at build time, read at startup.
# Pass via: docker build --build-arg BUILD_MARKER=<git-short-sha> ...
# Or via:   gcloud builds submit --substitutions=_BUILD_MARKER=<sha> ...
# The /app/BUILD_MARKER file is read by env_validator.read_build_marker()
# at startup; the value is then logged once and exposed on /health.
# ─────────────────────────────────────────────
ARG BUILD_MARKER=unknown
RUN echo "$BUILD_MARKER" > /app/BUILD_MARKER

# Install system dependencies
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for SQLite
RUN mkdir -p /app/data

# Expose port
EXPOSE 8080

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL=sqlite+aiosqlite:///./data/qa_bugbot.db
ENV PORT=8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8080/health'); assert r.status_code == 200"

# Start the server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
