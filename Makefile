# QRadar IOC Exporter — developer convenience targets
#
# Loads variables from .env (if present) so `sync-now`/`health` can authenticate.
-include .env

API_KEY      ?= changeme-secret-key
SERVICE_PORT ?= 8443
COMPOSE      ?= docker compose

.DEFAULT_GOAL := help
.PHONY: help build up down logs test sync-now health install run certs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

build: ## Build the Docker image
	$(COMPOSE) build

up: ## Start the service (detached)
	$(COMPOSE) up -d

down: ## Stop and remove the service
	$(COMPOSE) down

logs: ## Follow service logs
	$(COMPOSE) logs -f

test: ## Run the test suite
	pytest tests/ -v

sync-now: ## Trigger an immediate sync via the admin endpoint
	curl -sk -X POST \
		-H "Authorization: Bearer $(API_KEY)" \
		https://localhost:$(SERVICE_PORT)/admin/sync ; echo

health: ## Query the health endpoint
	curl -sk https://localhost:$(SERVICE_PORT)/health ; echo

install: ## Install dev dependencies into the current environment
	pip install -r requirements-dev.txt

run: ## Run the service locally (without Docker)
	python -m app.main

certs: ## Pre-generate the self-signed certificate
	python -c "from app.tls import ensure_certificate; ensure_certificate('certs')"

clean: ## Remove generated certs, logs and caches
	rm -rf certs logs .pytest_cache **/__pycache__
