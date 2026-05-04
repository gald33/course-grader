.PHONY: start up down logs status open restart backend-test backend-migrate backend-revision frontend-install

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
