.PHONY: setup test test-unit test-integration test-golden run down logs clean

setup:
	@if [ ! -f .env ]; then cp .env.example .env; echo "created .env from .env.example"; fi
	python -m pip install -e ".[dev]"

test: test-unit

test-unit:
	pytest tests/unit -q

test-golden:
	pytest tests/golden -q -m golden

test-integration:
	docker compose up -d --wait
	pytest tests/integration -q -m integration
	docker compose down

test-performance:
	pytest tests/performance -q -m performance

run:
	docker compose up -d --build --wait
	@echo "Ingestion API:    http://localhost:8000/docs"
	@echo "Human review UI:  http://localhost:8100/ui/review-tasks"
	@echo "MinIO console:    http://localhost:9001  (minioadmin / minioadmin)"
	@echo "Redpanda admin:   http://localhost:9644"

down:
	docker compose down

logs:
	docker compose logs -f

clean:
	docker compose down -v
.PHONY: evaluation
evaluation:
	python -m evaluation.runner --dataset dataset_raw --ground-truth evaluation_data/ground_truth.json --predictions evaluation_data/predictions.json --output evaluation_results
