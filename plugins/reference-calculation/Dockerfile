FROM ghcr.io/astral-sh/uv:0.11.15 AS uv
FROM python:3.14.4-slim

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/workspace/.venv
WORKDIR /workspace

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
COPY src src
COPY app app
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uv", "run", "--frozen", "python", "-m", "agent_hub_reference_calculation._server"]
