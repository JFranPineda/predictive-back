.PHONY: install up migrate bootstrap run worker test lint check

install:
	pip install -e ".[dev]"

up:
	docker compose up -d db redis minio

migrate:
	python manage.py migrate

bootstrap: migrate
	python manage.py modules bootstrap

run:
	python manage.py runserver 0.0.0.0:8000

worker:
	celery -A config worker -Q celery,media -l info

test:
	pytest

lint:
	ruff check . && ruff format --check .

# Hexagonal boundaries are a build gate, not a convention.
check: lint
	lint-imports
	mypy modules
	pytest
