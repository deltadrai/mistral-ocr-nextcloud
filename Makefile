.PHONY: help install-dev lint test validate check js-build js-check smoke \
        docker-build docker-push build run clean release update-schema

APP_IMAGE ?= ghcr.io/deltadrai/mistral-ocr-nextcloud
APP_TAG ?= latest
PYTHON ?= python3

# Vendored copy of the Nextcloud App Store schema; bump to refresh.
APPSTORE_REF ?= 83281c7965c78dce68daedacdc605ab8967cb6bd
APPSTORE_RAW := https://raw.githubusercontent.com/nextcloud/appstore/$(APPSTORE_REF)/nextcloudappstore/api/v1/release

help:
	@echo "install-dev    install runtime + dev dependencies"
	@echo "lint           ruff check + format check"
	@echo "test           pytest"
	@echo "validate       check appinfo/info.xml against the app-store schema"
	@echo "check          lint + test + validate + js bundle check (what CI runs)"
	@echo "js-build       bundle js/src/files_action.js -> js/files_action.js"
	@echo "docker-build   build the ExApp image"
	@echo "smoke          run the image and probe /api/v1/health"
	@echo "release        VERSION=x.y.z: bump every version, then tag and push"
	@echo "update-schema  re-download the vendored app-store schema files"

install-dev:
	$(PYTHON) -m pip install -r requirements-dev.txt

lint:
	ruff check src tests scripts
	ruff format --check src tests scripts

test:
	pytest -q

validate:
	$(PYTHON) scripts/validate_info_xml.py

js-build:
	npm run build

js-check:
	npm run check

check: lint test validate js-check

smoke: docker-build
	docker run -d --name mistral-ocr-smoke -p 9000:9000 $(APP_IMAGE):$(APP_TAG)
	@for i in $$(seq 1 30); do \
	  if curl -fsS http://127.0.0.1:9000/api/v1/health; then \
	    docker rm -f mistral-ocr-smoke >/dev/null; echo "smoke test passed"; exit 0; \
	  fi; sleep 1; \
	done; \
	echo "smoke test failed"; docker logs mistral-ocr-smoke; docker rm -f mistral-ocr-smoke; exit 1

docker-build:
	docker build --build-arg VERSION=$$($(PYTHON) -c "import xml.etree.ElementTree as ET; print(ET.parse('appinfo/info.xml').getroot().findtext('version'))") \
		--build-arg REVISION=$$(git rev-parse --short HEAD) \
		-t $(APP_IMAGE):$(APP_TAG) .

docker-push:
	docker push $(APP_IMAGE):$(APP_TAG)

build: docker-build

run:
	uvicorn src.main:app --host 127.0.0.1 --port 9000 --reload

# Bumps info.xml, package.json, __init__.py and CHANGELOG.md in one step.
release:
	@test -n "$(VERSION)" || { echo "usage: make release VERSION=x.y.z"; exit 1; }
	$(PYTHON) scripts/bump_version.py $(VERSION)
	@echo
	@echo "review the diff, then:"
	@echo "  git commit -am 'chore(release): v$(VERSION)'"
	@echo "  git tag v$(VERSION) && git push && git push --tags"

update-schema:
	curl -fsSL $(APPSTORE_RAW)/info.xsd -o scripts/schema/info.xsd
	curl -fsSL $(APPSTORE_RAW)/pre-info.xslt -o scripts/schema/pre-info.xslt
	@echo "updated scripts/schema from appstore@$(APPSTORE_REF)"

clean:
	rm -rf .pytest_cache .ruff_cache dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
