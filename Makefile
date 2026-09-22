.PHONY: setup test test-unit test-integration test-golden test-performance \
	architecture lint quality run down logs clean clean-runtime-data evaluation \
	prod-smoke prod-check prod-closeout-init ui-up ui-down ui-seed ui-up-local ui-down-local

setup:
	@if [ ! -f .env ]; then cp .env.example .env; echo "created .env from .env.example"; fi
	python -m pip install -e ".[dev]"

test: test-unit

test-unit:
	pytest tests/unit tests/architecture -q -p no:cacheprovider --basetemp=.test-tmp/pytest

test-golden:
	pytest tests/golden -q -m golden -p no:cacheprovider --basetemp=.test-tmp/golden

test-integration:
	docker compose up -d --wait
	pytest tests/integration -q -m integration -p no:cacheprovider --basetemp=.test-tmp/integration
	docker compose down

test-performance:
	pytest tests/performance -q -m performance -p no:cacheprovider --basetemp=.test-tmp/performance

architecture:
	python scripts/check_architecture.py

lint:
	ruff check apps packages workers evaluation scripts tests

quality: architecture lint test-unit

# Local development only (Compose + default MinIO). Not a production deploy.
run:
	docker compose up -d --build --wait
	@echo "Ingestion API:    http://localhost:8000/docs"
	@echo "Human review UI:  http://localhost:8100/ui/review-tasks"
	@echo "MinIO console:    http://localhost:9001  (minioadmin / minioadmin)"
	@echo "Redpanda admin:   http://localhost:9644"
	@echo "Evaluation UI:    http://localhost:8180"
	@echo ""
	@echo "Production/staging: docs/PRODUCTION_OPERATOR_RUNBOOK.md (Helm + secrets)"
	@echo "Fail-closed smoke:  make prod-smoke"

# Evaluation / HITL console with live API proxies (ingest + review).
UI_SERVICES = mysql minio redpanda redis \
	ingestion-api human-review-api human-review-task-worker \
	document-preparation-worker page-detection-worker \
	standard-form-extraction-worker validation-worker evaluation-ui

ui-up: ui-up-local

ui-up-compose:
	docker compose up -d --build --wait $(UI_SERVICES)
	@echo "Evaluation UI:    http://localhost:8180"
	@echo "Ingestion API:    http://localhost:8000/docs"
	@echo "Human review API: http://localhost:8100/ui/review-tasks"
	@echo "Seed demo queue:  make ui-seed"

ui-up-local:
	bash scripts/run_ui_local.sh

ui-down-local:
	@for f in /tmp/cdp-ui-logs/ingestion.pid /tmp/cdp-ui-logs/review.pid /tmp/cdp-ui-logs/ui.pid; do \
		if [ -f $$f ]; then kill $$(cat $$f) 2>/dev/null || true; rm -f $$f; fi; \
	done
	@echo "Stopped local UI stack"

ui-down:
	@$(MAKE) ui-down-local
	-docker compose stop $(UI_SERVICES)

ui-seed:
	@echo "Seeding demo document + HITL task into platform DB..."
	python3 scripts/seed_ui_demo_queue.py
	@echo "Open http://localhost:8180 — Work Queue / HITL should show the seeded task"

down:
	docker compose down

logs:
	docker compose logs -f

clean:
	python scripts/clean_workspace.py

# Destructive by design: unlike `clean`, this also removes local service data.
clean-runtime-data:
	docker compose down -v

evaluation:
	python -m evaluation.runner --dataset dataset_raw --ground-truth evaluation_data/ground_truth.json --predictions evaluation_data/predictions.json --output evaluation_results

# Production-hardened checks (local). Does NOT authorize PHI processing.
prod-smoke:
	python3 scripts/smoke_production_fail_closed.py

prod-closeout-init:
	python3 scripts/check_production_closeout.py --init

prod-check: prod-smoke
	@python3 scripts/check_production_closeout.py; status=$$?; \
	echo "Status remains production-hardened until closeout PROMOTE_TO_PRODUCTION."; \
	echo "See docs/PRODUCTION_READINESS.md and docs/PRODUCTION_OPERATOR_RUNBOOK.md"; \
	exit $$status
