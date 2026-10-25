# Lodestar developer commands. `make dev` runs everything locally (no Docker needed).
API := apps/api
PY := $(API)/.venv/bin/python
PSQL ?= psql

.PHONY: setup db migrate fixture api web worker seed dev test lint typecheck e2e contracts compose

setup:            ## install Python + Node dependencies
	python3 -m venv $(API)/.venv && $(API)/.venv/bin/pip install -q -r $(API)/requirements-dev.txt
	cd apps/web && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --no-audit --no-fund

db:               ## create roles and databases (local Postgres 16+)
	$(PSQL) -d postgres -f infra/db/init.sql
	-createdb aseo; -createdb aseo_test

migrate:
	cd $(API) && .venv/bin/alembic upgrade head

fixture:          ## WordPress companion-plugin test fixture on :8481
	$(PY) integrations/wordpress/fixture_server/server.py

api:
	cd $(API) && .venv/bin/uvicorn aseo.main:app --host 127.0.0.1 --port 8400 --reload

worker:           ## only for TASK_EXECUTION=celery
	cd $(API) && .venv/bin/celery -A aseo.worker.celery_app worker -B -l info

web:
	cd apps/web && npm run dev

seed:
	cd $(API) && .venv/bin/python -m aseo.seed

dev:              ## fixture + api + web (Ctrl-C stops all)
	@trap 'kill 0' INT; $(MAKE) fixture & sleep 1; $(MAKE) api & sleep 3; $(MAKE) web & wait

test:
	cd $(API) && .venv/bin/python -m pytest

lint:
	cd $(API) && .venv/bin/ruff check aseo tests migrations
	cd apps/web && npx next lint

typecheck:
	cd apps/web && npx tsc --noEmit

e2e:              ## requires `make dev` + `make seed` running
	cd apps/web && npx playwright test

contracts:        ## regenerate OpenAPI + TypeScript types
	$(PY) scripts/export_openapi.py
	cd apps/web && npm run gen:api

compose:
	docker compose up --build
