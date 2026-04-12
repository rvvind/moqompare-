# ─────────────────────────────────────────────
#  moqompare — task runner
# ─────────────────────────────────────────────

.PHONY: setup up down logs clean ps shell-source shell-packager shell-web cluster-credentials help

COMPOSE := $(shell if docker compose version >/dev/null 2>&1; then printf '%s' 'docker compose'; elif command -v docker-compose >/dev/null 2>&1; then printf '%s' 'docker-compose'; else printf '%s' 'docker compose'; fi)
ENV_FILE := .env

# ── Bootstrap ─────────────────────────────────────────────────────────────────

## Copy .env.example → .env (skip if already present), generate cluster auth, then pull images
setup:
	@if [ ! -f $(ENV_FILE) ]; then \
		cp .env.example $(ENV_FILE); \
		echo "Created .env from .env.example — edit it before running 'make up'"; \
	else \
		echo ".env already exists, skipping copy"; \
	fi
	@$(MAKE) cluster-credentials
	$(COMPOSE) pull

## Generate cluster_auth.jwk + cluster_token for fan-out subscriber auth
cluster-credentials:
	@python3 scripts/generate_cluster_credentials.py

# ── Lifecycle ─────────────────────────────────────────────────────────────────

## Start all services in the background
up:
	@$(MAKE) cluster-credentials
	$(COMPOSE) up -d

## Stop all services
down:
	$(COMPOSE) down

## Stream logs from all services (Ctrl-C to exit)
logs:
	$(COMPOSE) logs -f

## Show container status
ps:
	$(COMPOSE) ps

# ── Cleanup ───────────────────────────────────────────────────────────────────

## Stop services, remove containers + volumes, prune dangling images
clean:
	$(COMPOSE) down -v --remove-orphans
	docker image prune -f

# ── Debug helpers ─────────────────────────────────────────────────────────────

## Open a shell in the source container
shell-source:
	$(COMPOSE) exec source sh

## Open a shell in the packager container
shell-packager:
	$(COMPOSE) exec packager sh

## Open a shell in the web container
shell-web:
	$(COMPOSE) exec web sh

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "moqompare — available make targets:"
	@echo ""
	@echo "  setup          Copy .env.example → .env, generate cluster credentials, pull images"
	@echo "  up             Start all services (detached)"
	@echo "  down           Stop all services"
	@echo "  logs           Stream logs from all services"
	@echo "  ps             Show container status"
	@echo "  clean          Stop, remove containers+volumes, prune images"
	@echo "  shell-source   Shell into the source container"
	@echo "  shell-packager Shell into the packager container"
	@echo "  shell-web      Shell into the web container"
	@echo ""
