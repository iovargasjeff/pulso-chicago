FROM node:22-bookworm-slim AS frontend
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS backend
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api/ api/
FROM backend AS loader
COPY ingest/ ingest/
COPY sql/ sql/
COPY infra/seed_dokploy.py infra/seed_dokploy.py
CMD ["python", "-m", "infra.seed_dokploy"]

FROM backend AS runtime
COPY --from=frontend /ui/dist/ frontend/dist/
RUN useradd --create-home app
USER app
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
