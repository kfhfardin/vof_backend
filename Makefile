.PHONY: help install lint format type test unit integration e2e smoke smoke-full smoke-repair verify-hot-path skills-eval run worker compose-up compose-down migrate

help:
	@echo "Voice of the Field — make targets"
	@echo ""
	@echo "  install            uv sync"
	@echo "  lint               ruff check + mypy"
	@echo "  format             ruff format"
	@echo "  type               mypy app/"
	@echo "  test               pytest tests/unit (fast)"
	@echo "  unit               alias for test"
	@echo "  integration        tier-2 tests against compose"
	@echo "  e2e                tier-3 tests against compose + fake-AP"
	@echo "  smoke              third-party + infra reachability (cheap, ~2s)"
	@echo "  smoke-full         exercise every feature (~30s, costs cents)"
	@echo "  smoke-repair       PROBE=<name> for verbose diagnostics"
	@echo "  verify-hot-path    end-to-end latency check"
	@echo "  skills-eval        run every skills/<name>/evals/run.py"
	@echo "  run                uvicorn app.main:app --reload"
	@echo "  worker             arq app.workers.settings.PostCallWorker"
	@echo "  compose-up         docker compose -f docker-compose.local.yml up -d"
	@echo "  compose-down       docker compose -f docker-compose.local.yml down"
	@echo "  migrate            run both app + brain migrations to head"

install:
	uv sync

lint:
	uv run ruff check .
	uv run mypy app/

format:
	uv run ruff format .
	uv run ruff check --fix .

type:
	uv run mypy app/

test unit:
	uv run pytest tests/unit -q

integration:
	uv run pytest tests/integration -q

e2e:
	uv run pytest tests/e2e -q

smoke:
	uv run python -m smoke run --all --mode check

smoke-full:
	uv run python -m smoke run --all --mode smoke

smoke-repair:
	@if [ -z "$(PROBE)" ]; then echo "Usage: make smoke-repair PROBE=<name>"; exit 1; fi
	uv run python -m smoke.$(PROBE) --mode repair

verify-hot-path:
	uv run python -m scripts.verify_hot_path

skills-eval:
	@for skill_dir in skills/*/evals; do \
		if [ -f $$skill_dir/run.py ]; then \
			echo ">> $$skill_dir"; \
			uv run python $$skill_dir/run.py || exit 1; \
		fi \
	done

run:
	uv run uvicorn app.main:app --reload

worker:
	uv run arq app.workers.settings.PostCallWorker

compose-up:
	docker compose -f docker-compose.local.yml up -d

compose-down:
	docker compose -f docker-compose.local.yml down

migrate:
	uv run python -m scripts.alembic_wrapper app upgrade head
	uv run python -m scripts.alembic_wrapper brain upgrade head
