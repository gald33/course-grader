.PHONY: start up down logs status open restart backend-test backend-migrate backend-revision frontend-install deploy migrate-hosted worker-hosted

start:
	./scripts/bootstrap-macos.sh

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

status:
	docker compose ps
	@echo "Backend health:"
	@curl -fsS http://localhost:8000/api/health || true

open:
	./scripts/open-urls-macos.sh

restart: down up

backend-test:
	docker compose run --rm backend pytest -q

backend-migrate:
	docker compose run --rm backend alembic upgrade head

backend-revision:
	docker compose run --rm backend alembic revision --autogenerate -m "$(m)"

frontend-install:
	docker compose run --rm frontend npm install

# --- Hosted app (Vercel + Supabase) ------------------------------------------
# Vercel CLI logged in to the course's Vercel account in its own config dir:
#   vercel login --global-config ~/.vercel-yvc
VERCEL ?= vercel --global-config $(HOME)/.vercel-yvc

deploy:  ## deploy backend, then frontend, to production
	cd backend && $(VERCEL) link --yes --project course-grader-api >/dev/null && $(VERCEL) deploy --prod --yes
	cd frontend && $(VERCEL) link --yes --project course-grader >/dev/null && $(VERCEL) deploy --prod --yes

migrate-hosted:  ## apply migrations to the Supabase database (session pooler URL in .env)
	set -a; . ./.env; set +a; cd backend && DATABASE_URL="$$SUPABASE_POOL_URL" alembic upgrade head

worker-hosted:  ## run the notebook worker on this machine against the hosted database and storage
	set -a; . ./.env; set +a; docker compose run --rm -e DATABASE_URL="$$SUPABASE_POOL_URL" -e STORAGE_BACKEND=supabase worker
