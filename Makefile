.PHONY: clean
clean:
	rm -rf build dist __pycache__ .pytest_cache .coverage htmlcov .mypy_cache .ruff_cache

.PHONY: test
test:
	uv run pytest

.PHONY: lint
lint:
	uv run ruff check .

.PHONY: lint-fix
lint-fix:
	uv run ruff check --fix .

.PHONY: format
format:
	uv run ruff format .

.PHONY: format-check
format-check:
	uv run ruff format --check .

.PHONY: typecheck
typecheck:
	uv run mypy whisper_dictate

.PHONY: check
check: lint format-check typecheck test

.PHONY: fix
fix: lint-fix format

.PHONY: help
help:
	@echo "Available targets:"
	@echo "  clean           - Remove build artifacts and cache directories"
	@echo "  test            - Run pytest test suite; coverage is always on (pyproject addopts)"
	@echo "  lint            - Run ruff linting checks"
	@echo "  lint-fix        - Run ruff linting with auto-fix"
	@echo "  format          - Format code with ruff"
	@echo "  format-check    - Check code formatting without modifying"
	@echo "  typecheck       - Run mypy type checking"
	@echo "  check           - Run all checks (lint, format-check, typecheck, test)"
	@echo "  fix             - Auto-fix linting and formatting issues"
	@echo "  help            - Show this help message"
