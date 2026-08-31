# Single-stage: the dependency set is small and Render's free tier gives no
# build cache worth optimising for.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# argon2-cffi needs a compiler; the runtime does not.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Do not run as root. Render does not require it, an on-prem sysadmin will.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

# Shell form so $PORT is expanded: Render assigns the port and expects the
# container to bind it, while docker compose and a plain `docker run` have no
# PORT set and fall back to 8000 (which EXPOSE and the healthcheck use).
#
# Migrations run on every start. They are idempotent, and a container that
# boots against a schema it does not match is a worse failure than a few
# seconds of startup.
#
# The seed runs too, WITHOUT --reset. Without that flag it stops at "a plant
# already exists" and changes nothing, so a fresh database gets its demo data
# and a running one keeps whatever people have entered since. It still refuses
# outright unless ALLOW_REMOTE_SEED is set for the environment.
#
# One worker: Render free is 0.1 CPU / 512 MB, and argon2 hashing is
# memory-hard. A second worker would double peak memory for no throughput.
CMD ["sh", "-c", "python -m alembic upgrade head && python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
