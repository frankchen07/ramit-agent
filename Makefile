.PHONY: run-bot run-server pipeline install db-up db-down reset-memory

run-bot:
	python -m src.bot

run-server:
	cd knowledge && AGENT_PIPELINE_OUTPUT_DIR=output/ramit-sethi python -m src.server.mcp_server

pipeline:
	cd knowledge && python run_pipeline.py

install:
	pip install -e ".[dev]"

db-up:
	docker compose up -d

db-down:
	docker compose down

reset-memory:
	@echo "Dropping LangGraph checkpoint tables..."
	docker compose exec postgres psql -U ramit -d ramit -c \
		"DROP TABLE IF EXISTS checkpoints, checkpoint_writes, checkpoint_migrations CASCADE;"
	@echo "Done. Tables will be recreated on next bot start."
