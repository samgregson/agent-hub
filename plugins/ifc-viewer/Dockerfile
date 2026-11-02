FROM node:22.22.1-slim AS app-builder
WORKDIR /app
COPY app/package.json app/package-lock.json ./
RUN npm ci
COPY app ./
RUN npm run typecheck && npm test && npm run build

FROM ghcr.io/astral-sh/uv:0.11.15 AS uv
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/workspace/.venv
WORKDIR /workspace
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
COPY src src
COPY AGENT_GUIDE.md AGENT_GUIDE.md
COPY --from=app-builder /app/dist/index.html app/dist/index.html
RUN uv sync --frozen --no-dev && chmod -R a+rX /workspace
EXPOSE 8000
CMD ["/workspace/.venv/bin/python", "-m", "agent_hub_ifc_viewer._server"]
