# syntax=docker/dockerfile:1

# Multi-stage build for the survey demo.
#
#   base      : Python, environment settings, and the non-root user
#   builder   : runtime dependencies (requirements.txt) in a virtual environment
#   dev-deps  : builder plus dev dependencies (requirements-dev.txt)
#   dev       : image used only by docker-compose.dev.yml (Rung 1)
#   prod      : image used by docker-compose.yml (Rungs 2 and 3, and the VM)
#
# "prod" is the last stage, so a plain "docker build ." produces it.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Non-root user with a fixed UID/GID, identical on every host.
# /data is created here and owned by that user, so a new named volume
# mounted at /data inherits the correct ownership.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
 && mkdir /data \
 && chown app:app /data

WORKDIR /app


FROM base AS builder
RUN python -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt


FROM builder AS dev-deps
COPY requirements-dev.txt /tmp/requirements-dev.txt
RUN pip install -r /tmp/requirements-dev.txt


FROM base AS dev
COPY --from=dev-deps /opt/venv /opt/venv
# Lets pytest import the "app" package from /app.
ENV PYTHONPATH=/app
# The app user owns /app only so pytest can write its cache there.
# In the dev stack, app/, wsgi.py, and tests/ are bind-mounted over these paths.
RUN chown app:app /app
COPY app ./app
COPY wsgi.py ./
USER app
EXPOSE 5000
CMD ["flask", "--app", "wsgi", "run", "--debug", "--host", "0.0.0.0", "--port", "5000"]


FROM base AS prod
COPY --from=builder /opt/venv /opt/venv
# Code stays owned by root, so the app user can read it but not change it.
COPY app ./app
COPY wsgi.py ./

# OCI labels, filled in by CI (see .github/workflows/build-and-push.yml).
# Declared late so changing them does not invalidate the layers above.
ARG SOURCE_URL=""
ARG GIT_SHA=""
ARG BUILD_DATE=""
LABEL org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}"

USER app
EXPOSE 8000

# Uses only the standard library, so curl is not needed in the image.
# start-interval makes the first check run quickly, so nginx is not kept
# waiting for a full 30 second interval after startup.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --start-interval=2s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"]

# --no-control-socket: gunicorn 26+ otherwise opens a management socket in
# $HOME. The app user has no home directory and this demo does not use it.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "--no-control-socket", "wsgi:app"]
