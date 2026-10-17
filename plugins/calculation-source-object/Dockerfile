FROM node:22.22.1-slim AS app-builder
WORKDIR /app
COPY app/package.json app/package-lock.json ./
RUN npm ci
COPY app ./
RUN npm run build

FROM denoland/deno:2.9.7@sha256:fa335acdf6b72106eda2cb6a8cb5f4187e7630e357467489db4b2e7352d5e432 AS cso-runtime
ENV DENO_DIR=/deno-dir
WORKDIR /app
COPY app/deno.lock app/worker.mjs ./
RUN deno cache --frozen-lockfile worker.mjs

FROM python:3.14.4-slim AS cso-package
WORKDIR /package
RUN python -m pip download --disable-pip-version-check --no-deps --only-binary=:all: --dest /package cs-object==0.1.1 \
    && echo "b173dbc9e9ac1e06f8691ba20802b9fa2b5a1da3c3144768b9c0bac74e7e51ff  /package/cs_object-0.1.1-py3-none-any.whl" | sha256sum --check -

FROM ghcr.io/astral-sh/uv:0.11.15 AS uv
FROM python:3.14.4-slim

ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/workspace/.venv
WORKDIR /workspace

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
COPY src src
COPY app/index.html app/index.html
COPY --from=app-builder /app/dist/report.js app/dist/report.js
COPY --from=cso-runtime /usr/bin/deno /usr/bin/deno
COPY --from=cso-runtime /deno-dir /deno-dir
COPY --from=cso-runtime /app/worker.mjs /app/worker.mjs
COPY --from=cso-runtime /app/deno.lock /app/deno.lock
COPY --from=cso-package /package/cs_object-0.1.1-py3-none-any.whl /app/cs_object.whl
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["/workspace/.venv/bin/python", "-m", "agent_hub_calculation_source_object._server"]
