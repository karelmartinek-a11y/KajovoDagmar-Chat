FROM node:22.23.2-bookworm-slim@sha256:f32b81066cde10a75dbac96646099533316d94bac4150c55da1636e1f0ffdc46 AS web-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

FROM python:3.12.13-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d AS python-build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 UV_NO_PROGRESS=1
WORKDIR /opt/kajovodagmar
RUN apk add --no-cache build-base cargo libffi-dev openssl-dev postgresql-dev \
    && python -m pip install uv==0.12.0
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src/ src/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.13-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/kajovodagmar/.venv/bin:/opt/kajovodagmar/bin:$PATH
RUN addgroup -S -g 10001 kajovodagmar \
    && adduser -S -D -H -u 10001 -G kajovodagmar -s /sbin/nologin kajovodagmar \
    && apk add --no-cache ca-certificates libpq
WORKDIR /opt/kajovodagmar
COPY --from=python-build /opt/kajovodagmar/.venv .venv
COPY migrations/ migrations/
COPY alembic.ini ./
COPY --from=web-build /build/web/dist web/dist/
RUN mkdir -p runtime/logs runtime/exports && chown -R kajovodagmar:kajovodagmar /opt/kajovodagmar
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python","-c","import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=3)"]
CMD ["uvicorn","kajovodagmar.main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips=*"]
