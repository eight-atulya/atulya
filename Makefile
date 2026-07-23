# Atulya developer command surface.
#
# This file intentionally stays thin: scripts/ remains the source of truth for
# lifecycle, release, migration, and generation behavior. Make only provides a
# memorable, consistent entry point for common local and CI tasks.

SHELL := /bin/sh
.DEFAULT_GOAL := help

# Resolve paths from this file so `make -C <repo>` and calls from subdirectories
# behave the same as calls from the repository root.
ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
API_DIR := $(ROOT_DIR)/atulya-api
CONTROL_PLANE_DIR := $(ROOT_DIR)/atulya-control-plane
DOCS_DIR := $(ROOT_DIR)/atulya-docs

# These can be overridden for managed development environments, for example:
# `make UV=/opt/uv/bin/uv install`.
UV ?= uv
NPM ?= npm

.PHONY: help check-tools check-python-tools check-node-tools check-dev-tools bootstrap init-env install \
        dev atulya stack api ui worker docs \
        test test-api test-api-focused typecheck lint verify \
        format format-api format-ui build build-ui build-docs \
        migrate admin openapi clients clean

help: ## Show the available commands
	@printf '%s\n' 'Atulya commands:'
	@awk 'BEGIN { FS = ":.*## " } /^[a-zA-Z0-9_.-]+:.*## / { printf "  %-20s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf '\n%s\n' 'Examples:'
	@printf '%s\n' '  make bootstrap        Install dependencies for a new checkout'
	@printf '%s\n' '  make dev              Start API and control plane together'
	@printf '%s\n' '  make test-api ARGS="tests/test_admin_auth.py -q"'
	@printf '%s\n' '  make admin           Open the interactive admin menu'
	@printf '%s\n' '  make admin ARGS="list-platform-admins"'

check-python-tools: ## Check the Python toolchain used by API and admin commands
	@set -eu; \
	for command in "$(UV)"; do \
		command -v "$$command" >/dev/null 2>&1 || { \
			printf '%s\n' "Missing required command: $$command" >&2; \
			exit 1; \
		}; \
	done; \
	printf '%s\n' 'Python tools found: uv'

check-node-tools: ## Check the Node.js toolchain used by UI and docs commands
	@set -eu; \
	for command in "$(NPM)"; do \
		command -v "$$command" >/dev/null 2>&1 || { \
			printf '%s\n' "Missing required command: $$command" >&2; \
			exit 1; \
		}; \
	done; \
	printf '%s\n' 'Node tools found: npm'

check-tools: check-python-tools check-node-tools ## Check Python and Node.js toolchains

check-dev-tools: check-python-tools ## Check tools required to run the API locally
	@set -eu; \
	for command in python3 curl; do \
		command -v "$$command" >/dev/null 2>&1 || { \
			printf '%s\n' "Missing required command: $$command" >&2; \
			exit 1; \
		}; \
	done; \
	printf '%s\n' 'Local service tools found: python3, curl'

bootstrap: check-tools ## Install Python and Node dependencies for a new checkout
	@test -f "$(ROOT_DIR)/.env" || printf '%s\n' 'No .env found. Run `make init-env`, then configure it before starting Atulya.'
	@cd "$(ROOT_DIR)" && "$(UV)" sync --directory atulya-api
	@cd "$(ROOT_DIR)" && "$(NPM)" install

init-env: ## Create .env from .env.example without overwriting an existing file
	@if [ -f "$(ROOT_DIR)/.env" ]; then \
		printf '%s\n' '.env already exists; leaving it unchanged.'; \
	elif [ -f "$(ROOT_DIR)/.env.example" ]; then \
		cp "$(ROOT_DIR)/.env.example" "$(ROOT_DIR)/.env"; \
		printf '%s\n' 'Created .env from .env.example. Review secrets and auth settings before use.'; \
	else \
		printf '%s\n' 'Cannot create .env: .env.example is missing.' >&2; \
		exit 1; \
	fi

install: check-tools ## Install or synchronize all primary project dependencies
	@cd "$(ROOT_DIR)" && "$(UV)" sync --directory atulya-api
	@cd "$(ROOT_DIR)" && "$(NPM)" install

# Lifecycle targets delegate to the existing scripts, which load .env, perform
# readiness checks, resolve ports, and shut down child processes consistently.
dev: check-dev-tools check-node-tools ## Start the API and control plane
	@cd "$(ROOT_DIR)" && ./scripts/dev/start.sh

api: check-dev-tools ## Start only the API
	@cd "$(ROOT_DIR)" && ./scripts/dev/start-api.sh

ui: check-node-tools ## Start only the control plane
	@cd "$(ROOT_DIR)" && ./scripts/dev/start-control-plane.sh

worker: check-python-tools ## Start the background worker
	@cd "$(ROOT_DIR)" && ./scripts/dev/start-worker.sh

docs: check-node-tools ## Start the documentation site
	@cd "$(ROOT_DIR)" && ./scripts/dev/start-docs.sh

atulya: check-dev-tools check-node-tools ## Start API, control plane, and worker together
	@cd "$(ROOT_DIR)" && ./scripts/dev/start.sh --with-worker

# Keep the previous name as a compatibility alias for local scripts and habits.
stack: atulya

test: test-api ## Run the default backend test suite

test-api: check-python-tools ## Run backend tests; pass extra options with ARGS='...'
	@cd "$(API_DIR)" && "$(UV)" run pytest tests/ $(ARGS)

test-api-focused: check-python-tools ## Run focused auth/admin tests
	@cd "$(API_DIR)" && "$(UV)" run pytest tests/test_admin_auth.py tests/test_auth_sessions.py tests/test_access_grants.py $(ARGS)

typecheck: check-node-tools ## Type-check the control plane
	@cd "$(CONTROL_PLANE_DIR)" && "$(NPM)" run typecheck

lint: check-tools ## Run the repository's canonical lint and formatting hook
	@cd "$(ROOT_DIR)" && ./scripts/hooks/lint.sh

verify: ## Run the standard pre-ship checks
	@$(MAKE) lint
	@$(MAKE) typecheck
	@$(MAKE) test-api

format: format-api format-ui ## Format Python and control-plane sources

format-api: check-python-tools ## Format Python sources with Ruff
	@cd "$(API_DIR)" && "$(UV)" run ruff format .

format-ui: check-node-tools ## Format control-plane TypeScript sources
	@cd "$(CONTROL_PLANE_DIR)" && "$(NPM)" exec -- prettier --write 'src/**/*.{ts,tsx}'

build: build-ui build-docs ## Build the control plane and documentation

build-ui: check-node-tools ## Build the production control-plane bundle
	@cd "$(CONTROL_PLANE_DIR)" && "$(NPM)" run build

build-docs: check-node-tools ## Build the documentation site
	@cd "$(DOCS_DIR)" && "$(NPM)" run build

migrate: check-python-tools ## Apply database migrations using the Atulya admin CLI
	@cd "$(API_DIR)" && "$(UV)" run atulya-admin run-db-migration

admin: check-python-tools ## Open the admin menu, or run a CLI command via ARGS='...'
	@if [ -n "$(strip $(ARGS))" ]; then \
		cd "$(API_DIR)" && "$(UV)" run atulya-admin $(ARGS); \
	else \
		cd "$(ROOT_DIR)" && UV="$(UV)" sh ./scripts/dev/admin-menu.sh; \
	fi

openapi: check-tools ## Regenerate OpenAPI and API documentation
	@cd "$(ROOT_DIR)" && ./scripts/generate-openapi.sh

clients: check-tools ## Regenerate the supported client SDKs
	@cd "$(ROOT_DIR)" && ./scripts/generate-clients.sh

clean: ## Remove generated local build output, never source or dependency data
	@rm -rf \
		"$(CONTROL_PLANE_DIR)/.next" \
		"$(CONTROL_PLANE_DIR)/standalone" \
		"$(DOCS_DIR)/build" \
		"$(DOCS_DIR)/.docusaurus"
	@printf '%s\n' 'Removed local UI and documentation build output.'
