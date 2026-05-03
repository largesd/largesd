PYTHON ?= python3

.PHONY: bootstrap test unit fact server smoke acceptance lint format

bootstrap:
	$(PYTHON) scripts/dev_workflow.py bootstrap

test:
	$(PYTHON) scripts/dev_workflow.py check

unit:
	$(PYTHON) scripts/dev_workflow.py unit

fact:
	$(PYTHON) scripts/dev_workflow.py fact

server:
	$(PYTHON) scripts/dev_workflow.py server --version v3

smoke:
	$(PYTHON) scripts/dev_workflow.py smoke

acceptance:
	$(PYTHON) scripts/dev_workflow.py acceptance

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m black .
