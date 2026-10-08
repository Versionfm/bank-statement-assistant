.PHONY: install test lint typecheck frontend-build verify

install:
	uv sync --locked
	npm --prefix frontend ci

test:
	uv run pytest
	npm --prefix frontend test

lint:
	uv run ruff check src tests migrations
	uv run ruff format --check src tests migrations
	npm --prefix frontend run format:check
	npm --prefix frontend run lint

typecheck:
	uv run mypy src
	npm --prefix frontend run typecheck

frontend-build:
	npm --prefix frontend run build

verify: lint typecheck test frontend-build
