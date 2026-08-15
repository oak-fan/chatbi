PYTHON ?= .venv/bin/python
LIMIT ?= 100
PRESET ?= target-v3
TIMEOUT ?= 180
RUN_ID ?=
RESUME_RUN_ID ?=

.PHONY: help install bench bench-quick bench-baseline bench-resume analyze probe import-bird migrate

help:
	@echo "Targets:"
	@echo "  make install          Install dependencies into .venv"
	@echo "  make migrate          Run alembic upgrade head"
	@echo "  make import-bird      Import BIRD-MINIDEV dataset"
	@echo "  make bench            Run benchmark (LIMIT=$(LIMIT), PRESET=$(PRESET))"
	@echo "  make bench-quick      Run 10-sample quick benchmark"
	@echo "  make bench-baseline   Run baseline preset (100 samples)"
	@echo "  make bench-resume     Resume run by RESUME_RUN_ID"
	@echo "  make analyze          Analyze latest or RUN_ID artifact"
	@echo "  make probe            Probe DB / dataset readiness"

install:
	bash _install_deps.sh

migrate:
	bash _run_alembic.sh

import-bird:
	bash _import_bird.sh

bench:
	PYTHONPATH=. $(PYTHON) scripts/bench_bird.py --preset $(PRESET) --limit $(LIMIT) --timeout $(TIMEOUT)

bench-quick:
	PYTHONPATH=. $(PYTHON) scripts/bench_bird.py --preset $(PRESET) --limit 10 --timeout $(TIMEOUT)

import-qsql:
	bash _import_bird_qsql.sh --limit 5000

bench-baseline:
	PYTHONPATH=. $(PYTHON) scripts/bench_bird.py --preset baseline --limit 100 --timeout $(TIMEOUT)

bench-resume:
	@test -n "$(RESUME_RUN_ID)" || (echo "RESUME_RUN_ID is required, e.g. make bench-resume RESUME_RUN_ID=123"; exit 1)
	PYTHONPATH=. $(PYTHON) scripts/bench_bird.py --resume-run-id $(RESUME_RUN_ID) --timeout $(TIMEOUT)

analyze:
	PYTHONPATH=. $(PYTHON) scripts/analyze_failures.py $(if $(RUN_ID),--run-id $(RUN_ID),--latest)

probe:
	PYTHONPATH=. $(PYTHON) scripts/bench_bird.py --probe
