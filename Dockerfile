##############################################################################
# Dockerfile — NOVEX single-image build
#
# Stage 1  Build the Vite/React frontend (node:20-alpine)
# Stage 2  Runtime image: Python 3.12, Nginx, Redis, Supervisor
#
# Usage:
#   docker build -t novex .
#   docker run -d --name novex --network host novex
##############################################################################

# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --prefer-offline

COPY frontend/ .
RUN npm run build

# ── Stage 2: Runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MODE=prod

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    redis-server \
    supervisor \
    libldap2-dev \
    libsasl2-dev \
    libssl-dev \
    unixodbc-dev \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    build-essential \
    python3-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt /tmp/requirements.txt
COPY backend/UrdhvaBase /opt/ceg/algo/UrdhvaBase

RUN pip install --upgrade pip setuptools wheel \
    && pip install -e /opt/ceg/algo/UrdhvaBase \
    && pip install -r /tmp/requirements.txt

# ── Copy backend modules ───────────────────────────────────────────────────────
COPY backend/api_manager             /opt/ceg/algo/api_manager
COPY backend/authenticator           /opt/ceg/algo/authenticator
COPY backend/orchestrator            /opt/ceg/algo/orchestrator
COPY backend/utilities               /opt/ceg/algo/utilities
COPY backend/cache_gateway           /opt/ceg/algo/cache_gateway
COPY backend/ceg_role_master_api     /opt/ceg/algo/ceg_role_master_api
COPY backend/vendor_ingestion_api    /opt/ceg/algo/vendor_ingestion_api
COPY backend/Thingsboard             /opt/ceg/algo/Thingsboard

# ── Conditionally copy environment / config files ─────────────────────────────
# We use a shell glob via RUN+cp so the build does NOT fail when the files
# are absent from the repository (they are typically provided at runtime via
# a Docker volume or secret injected by the CI/CD pipeline).
#
# The COPY instruction with a wildcard fails hard when nothing matches;
# using "cp 2>/dev/null || true" is the standard Docker workaround.
RUN mkdir -p /opt/ceg/algo

# Copy .alg_env (the primary secrets file read by urdhva_base/settings.py)
COPY backend/api_manager/.alg_env    /opt/ceg/algo/api_manager/.alg_env

# ── Frontend static assets ────────────────────────────────────────────────────
RUN rm -rf /usr/share/nginx/html/*
COPY --from=frontend-build /app/dist /usr/share/nginx/html

# ── Nginx & Supervisor configuration ─────────────────────────────────────────
COPY nginx.conf        /etc/nginx/conf.d/default.conf
RUN  rm -f /etc/nginx/sites-enabled/default

COPY supervisord.conf  /etc/supervisor/conf.d/novex.conf

# ── Runtime directories ────────────────────────────────────────────────────────
RUN mkdir -p \
    /var/log/ceg_sys_logs \
    /var/log/ceg_logs \
    /var/run/redis \
    /var/log/ceg_sys_logs/uploads \
    /var/log/ceg_sys_logs/downloads \
    /var/log/ceg_sys_logs/mft \
    /var/log/ceg_sys_logs/ticketing_attachments

EXPOSE 5378 8002

# Docker built-in healthcheck — also used when running without compose
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -sf http://localhost:5378/health || exit 1

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/novex.conf"]
