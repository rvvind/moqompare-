# ─────────────────────────────────────────────
#  moqompare — task runner
# ─────────────────────────────────────────────

.PHONY: setup up down logs clean ps shell-source shell-packager shell-web cluster-credentials help

COMPOSE := docker compose
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
	@python3 - << 'PYEOF'
import base64, hmac, hashlib, json, os, sys
def b64url(d):
    return base64.urlsafe_b64encode(d if isinstance(d,bytes) else d.encode()).rstrip(b'=').decode()
if os.path.exists('cluster_auth.jwk') and os.path.exists('cluster_token'):
    print("cluster_auth.jwk + cluster_token already exist, skipping")
    sys.exit(0)
secret = os.urandom(32)
k = b64url(secret)
jwk = {"kty":"oct","k":k,"alg":"HS256","key_ops":["sign","verify"]}
header  = b64url(json.dumps({"alg":"HS256","typ":"JWT"},separators=(',',':')))
payload = b64url(json.dumps({"cluster":True,"put":[""],"get":[""],"exp":4102444800},separators=(',',':')))
sig     = hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest()
jwt     = f"{header}.{payload}.{b64url(sig)}"
with open('cluster_auth.jwk','w') as f: json.dump(jwk,f,separators=(',',':'))
with open('cluster_token','w') as f: f.write(jwt)
print("Generated cluster_auth.jwk and cluster_token")
PYEOF

# ── Lifecycle ─────────────────────────────────────────────────────────────────

## Start all services in the background
up:
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
