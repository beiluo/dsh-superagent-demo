PYTHON ?= python3

.PHONY: validate build serve

validate:
	$(PYTHON) scripts/validate.py

build:
	$(PYTHON) scripts/build_data.py

serve:
	$(PYTHON) -m http.server 8000
