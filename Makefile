# Ontic 一键命令
.PHONY: up down dev install seed health

up:
	docker compose up -d --build

down:
	docker compose down

install:
	python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt

dev:
	cd backend && uvicorn app.main:app --reload --port 8000

seed:
	cd backend && python -m app.seed

health:
	curl -s localhost:8080/api/health
