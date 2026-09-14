.PHONY: acceptance architecture-check build contracts contracts-check dev down format format-check lint migrate setup test typecheck

export UV_CACHE_DIR := $(CURDIR)/.cache/uv
export npm_config_cache := $(CURDIR)/.cache/npm

PNPM := npm exec --yes --package=pnpm@12.4.1 -- pnpm

setup:
	$(PNPM) install --frozen-lockfile
	uv sync --frozen --all-packages

dev:
	docker compose up --build

down:
	docker compose down

build:
	$(PNPM) build

architecture-check:
	$(PNPM) architecture:check

contracts:
	$(PNPM) contracts:generate

contracts-check:
	$(PNPM) contracts:check

format:
	$(PNPM) format

format-check:
	$(PNPM) format:check

lint:
	$(PNPM) lint

typecheck:
	$(PNPM) typecheck

test:
	$(PNPM) test

migrate:
	uv run --package agent-hub-api alembic -c apps/api/alembic.ini upgrade head

acceptance:
	$(MAKE) contracts-check
	$(MAKE) format-check
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test
	$(MAKE) build
