PYTHON ?= python3
DATE ?= $(shell $(PYTHON) -c "import json; print(json.load(open('catalog/snapshot.json'))['captured_at'][:10])")
.PHONY: install validate test test-browser build serve release
install:
	$(PYTHON) -m pip install -r requirements.txt
	npm --prefix dashboard ci
	cd dashboard && npx playwright install chromium
validate:
	$(PYTHON) pipeline/validate.py --strict-description
	$(PYTHON) scripts/check_public.py

test:
	$(PYTHON) -m pytest pipeline/tests scripts/tests -q
	cd dashboard && npm run test:props

test-browser:
	cd dashboard && npm test

build:
	$(PYTHON) scripts/build_site.py --date $(DATE)

serve:
	$(PYTHON) -m http.server 8789 --bind 127.0.0.1 --directory dashboard/dist

release:
	$(PYTHON) scripts/package_release.py
