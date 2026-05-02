.PHONY: up down test lint typecheck env-check measure-llm clean

up:
	docker compose up -d
	@echo "Waiting for healthchecks..."
	@docker compose ps

down:
	docker compose down

test:
	pytest tests/ services/

lint:
	ruff check .

typecheck:
	mypy services/

env-check:
	@./scripts/check-env.sh

measure-llm:
	python scripts/measure_llm_throughput.py

clean:
	docker compose down -v
	rm -rf .pytest_cache .mypy_cache .ruff_cache
