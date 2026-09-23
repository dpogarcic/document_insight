.PHONY: local-run format format-check lint test test-integration test-e2e quality

# Start the complete local stack (docs/README.md's `docker compose up --build`).
local-run:
	docker compose up --build

format:
	uv run ruff format src tests migrations

format-check:
	uv run ruff format --check src tests migrations

lint:
	uv run ruff check src tests migrations
	uv run mypy

# Unit tests only (tests/api, tests/application, tests/infrastructure,
# tests/observability, tests/benchmark); already clears the 70% branch-coverage gate
# on its own.
test:
	uv run pytest tests/api tests/application tests/infrastructure tests/observability tests/benchmark

# Requires the disposable database-test/redis-test services (README's "Disposable
# PostgreSQL security tests"); skips cleanly if their *_URL env vars are unset.
test-integration:
	uv run pytest -q -o addopts='' tests/integration

test-e2e:
	uv run pytest -q -o addopts='' tests/e2e

quality: format-check lint test test-integration test-e2e
