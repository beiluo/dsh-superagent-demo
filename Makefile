VENV ?= .venv
PYTHON ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
UV ?= uv

.PHONY: setup validate check-secrets build serve agent test

setup:
	$(UV) venv $(VENV) --python 3.12
	$(UV) pip install --python $(VENV)/bin/python -r requirements.txt -r requirements-dev.txt

validate: check-secrets
	$(PYTHON) scripts/validate.py

check-secrets:
	$(PYTHON) scripts/check_no_secrets.py

build:
	$(PYTHON) scripts/build_data.py

serve:
	$(PYTHON) -m http.server 8000

agent:
	$(VENV)/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000

test:
	$(VENV)/bin/python -m pytest -q
