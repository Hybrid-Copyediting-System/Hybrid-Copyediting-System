# syntax=docker/dockerfile:1.7

# ---- Stage 1: build the Vue/Vite SPA ----
FROM node:20-alpine AS frontend
WORKDIR /build

# Cache deps separately from sources for faster rebuilds.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build
# → /build/dist now contains the production SPA bundle.


# ---- Stage 2: Python runtime serving API + SPA on one port ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/ets_checker ./ets_checker

# Editable install so server.py's `Path(__file__).parent / "frontend_dist"`
# resolves to /app/ets_checker/frontend_dist (rather than site-packages).
RUN pip install --upgrade pip && pip install -e .

# Drop the built SPA where server.py auto-mounts it via StaticFiles.
COPY --from=frontend /build/dist ./ets_checker/frontend_dist

# ETS_PORT is overridable via compose / `docker run -e ETS_PORT=...`.
ENV ETS_PORT=47823
EXPOSE 47823

# /bin/sh so $ETS_PORT expands at runtime, not build time.
CMD ["sh", "-c", "exec uvicorn ets_checker.server:app --host 0.0.0.0 --port ${ETS_PORT}"]
