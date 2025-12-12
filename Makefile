PYINSTALLER_SPEC ?= packaging/pyinstaller/whisper_dictate_gui.spec
USE_UV ?= 1

PYINSTALLER ?= pyinstaller

ifeq ($(USE_UV),1)
PYINSTALLER := uv run pyinstaller
UV_RUN := uv run
else
UV_RUN :=
endif

.PHONY: build-exe
build-exe:
	$(PYINSTALLER) $(PYINSTALLER_SPEC) --noconfirm

.PHONY: clean
clean:
	rm -rf build dist *.spec __pycache__ .pytest_cache .coverage htmlcov .mypy_cache .ruff_cache

.PHONY: test
test:
	$(UV_RUN) pytest

.PHONY: test-coverage
test-coverage:
	$(UV_RUN) pytest --cov=whisper_dictate --cov-report=term-missing --cov-report=html

.PHONY: lint
lint:
	$(UV_RUN) ruff check .

.PHONY: lint-fix
lint-fix:
	$(UV_RUN) ruff check --fix .

.PHONY: format
format:
	$(UV_RUN) ruff format .

.PHONY: format-check
format-check:
	$(UV_RUN) ruff format --check .

.PHONY: typecheck
typecheck:
	$(UV_RUN) mypy whisper_dictate

.PHONY: check
check: lint format-check typecheck test

.PHONY: fix
fix: lint-fix format

.PHONY: help
help:
	@echo "Available targets:"
	@echo "  build-exe       - Build Windows executable with PyInstaller"
	@echo "  clean           - Remove build artifacts and cache directories"
	@echo "  test            - Run pytest test suite"
	@echo "  test-coverage   - Run tests with coverage report (HTML + terminal)"
	@echo "  lint            - Run ruff linting checks"
	@echo "  lint-fix        - Run ruff linting with auto-fix"
	@echo "  format          - Format code with ruff"
	@echo "  format-check    - Check code formatting without modifying"
	@echo "  typecheck       - Run mypy type checking"
	@echo "  check           - Run all checks (lint, format-check, typecheck, test)"
	@echo "  fix             - Auto-fix linting and formatting issues"
	@echo "  help            - Show this help message"
