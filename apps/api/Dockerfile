FROM ghcr.io/astral-sh/uv:0.11.15 AS uv
FROM python:3.14.4-slim

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/workspace/.venv
WORKDIR /workspace

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/src apps/api/src
RUN uv sync --frozen --no-dev --package agent-hub-api

EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-dev", "--package", "agent-hub-api", "uvicorn", "agent_hub_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
