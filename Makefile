# Run from Linux, macOS, WSL or Git Bash. With an activated virtualenv (VIRTUAL_ENV set)
# the targets use its `python`; otherwise they use $(VENV)/bin/python.
# `make install VENV=$HOME/.venvs/inventory` creates the environment elsewhere
# (recommended when the repo lives in a OneDrive/Dropbox-synced folder).
VENV ?= .venv
PY := $(if $(VIRTUAL_ENV),python,$(VENV)/bin/python)
PORT_API ?= 8080
PORT_PROCESSOR ?= 8081

.DEFAULT_GOAL := help
.PHONY: help install run-api run-processor test cov lint format typecheck check docker-api docker-processor clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Create the virtualenv and install the project with dev tools
ifeq ($(shell command -v uv 2>/dev/null),)
	python3 -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/bin/python -m pip install -e ".[dev]"
else
	uv venv --python 3.12 $(VENV)
	uv pip install --python $(VENV)/bin/python -e ".[dev]"
endif

run-api: ## Run inventory-api locally with Flask's reloader
	PORT=$(PORT_API) $(PY) -m flask --app "api.app:create_app" run --debug --port $(PORT_API)

run-processor: ## Run inventory-processor locally with Flask's reloader
	PORT=$(PORT_PROCESSOR) $(PY) -m flask --app "processor.app:create_app" run --debug --port $(PORT_PROCESSOR)

test: ## Run the test suite
	$(PY) -m pytest

cov: ## Run the tests with a coverage report
	$(PY) -m pytest --cov=api --cov=processor --cov=common --cov-report=term-missing

lint: ## Lint and check formatting
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format: ## Auto-fix lint issues and format the code
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

typecheck: ## Type-check with mypy (strict)
	$(PY) -m mypy

check: lint typecheck test ## Everything CI runs

docker-api: ## Build the inventory-api image
	docker build -f docker/api.Dockerfile -t inventory-api:local .

docker-processor: ## Build the inventory-processor image
	docker build -f docker/processor.Dockerfile -t inventory-processor:local .

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache build *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
