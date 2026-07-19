# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so the layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user. This matters here specifically because run_python
# executes model-generated code in a subprocess — as root it could write
# anywhere in the container.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/uploads /app/data/datasets \
    && chown -R appuser:appuser /app
USER appuser

# DuckDB extensions (postgres/mysql/sqlite) are downloaded on first use and
# cached in the home directory, which must be writable by appuser.
ENV HOME=/home/appuser

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3).status==200 else 1)"

CMD ["uvicorn", "api:apps", "--host", "0.0.0.0", "--port", "8090"]
