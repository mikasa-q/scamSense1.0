FROM node:24-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS frontend
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/public/ ./public/
COPY frontend/src/ ./src/
RUN npm run build

FROM python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY alembic.ini ./
COPY backend/ ./backend/
COPY migrations/ ./migrations/
COPY --from=frontend /web/dist/ ./frontend/dist/
RUN groupadd --gid 10001 scamsense \
    && useradd --uid 10001 --gid 10001 --no-create-home --no-log-init scamsense \
    && install -d -o 10001 -g 10001 -m 0700 /app/data
USER 10001:10001
VOLUME ["/app/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8765/api/health', timeout=3).close()"]
CMD ["sh", "-c", "python -m alembic upgrade head && exec python -m uvicorn backend.main:create_app --factory --host 0.0.0.0 --port 8765 --no-access-log"]
