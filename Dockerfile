# The platform: FastAPI and the scheduler in one process (spec §4.1).
# The same Python as CI and the venv: one version, not a range (spec §14).
FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY engine engine
COPY exchange exchange
COPY core core
COPY api api
COPY scripts scripts

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin coinpilot
USER coinpilot

EXPOSE 8000

# No curl in a slim image; Python is there anyway.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# The graceful timeout covers open requests; the scheduler's stop runs after it, and the
# compose file's stop_grace_period covers both.
CMD ["uvicorn", "--factory", "api.main:build", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "60"]

LABEL org.opencontainers.image.source="https://github.com/jAjiz/coinpilot" \
      org.opencontainers.image.description="CoinPilot platform"
