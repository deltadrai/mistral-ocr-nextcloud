.PHONY: build run test lint install-dev docker-build docker-push clean

APP_IMAGE ?= ghcr.io/deltadrai/mistral-ocr-nextcloud
APP_TAG ?= latest

install-dev:
	pip install -r requirements.txt -r requirements-dev.txt

lint:
	ruff check src tests
	ruff format --check src tests

test:
	pytest -q

docker-build:
	docker build -t $(APP_IMAGE):$(APP_TAG) .

docker-push:
	docker push $(APP_IMAGE):$(APP_TAG)

build: docker-build

run:
	uvicorn src.main:app --host 127.0.0.1 --port 9000 --reload

clean:
	rm -rf .pytest_cache .ruff_cache dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
