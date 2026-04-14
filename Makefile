PYTHON ?= python3
WORKFLOW := scripts/dev_workflow.py
AGENTIC := scripts/agentic_workflow.py
GOAL ?= Drive debate_system through a human-AI workflow with explicit checkpoints.
NOTE ?= approved

.PHONY: help bootstrap status resume review-prompts check unit fact smoke e2e server server-v1 server-v2 server-fast manual-ai manual-energy modulation openrouter-setup executor-bootstrap

help:
	@printf "%s\n" \
		"Available targets:" \
		"  bootstrap       Create agentic workflow scaffolding" \
		"  status          Show the current workflow phase" \
		"  resume          Advance to the next workflow phase" \
		"  review-prompts  Review logged human prompts and suggest workflow improvements" \
		"  executor-bootstrap Install Python dependencies into the repo venv" \
		"  check           Run unit and fact-check test suites" \
		"  unit            Run test_debate_system.py" \
		"  fact            Run test_fact_check_skill.py" \
		"  smoke           Start a temporary v3 server and run a health-check scenario" \
		"  acceptance      Start a temporary server and run the browser acceptance suite" \
		"  e2e             Start a temporary server and run the AI scenario" \
		"  server          Start the v3 server" \
		"  server-v1       Start the v1 server" \
		"  server-v2       Start the v2 server" \
		"  server-fast     Start the fast v2 server" \
		"  manual-ai       Run the AI scenario against an existing server" \
		"  manual-energy   Run the energy scenario against an existing server" \
		"  modulation      Run the moderation scenario against an existing server" \
		"  openrouter-setup Run the interactive OpenRouter setup helper"

bootstrap:
	$(PYTHON) $(AGENTIC) bootstrap --goal "$(GOAL)"

status:
	$(PYTHON) $(AGENTIC) status

resume:
	$(PYTHON) $(AGENTIC) resume --human-note "$(NOTE)"

review-prompts:
	$(PYTHON) $(AGENTIC) review-prompts

executor-bootstrap:
	$(PYTHON) $(WORKFLOW) bootstrap

check:
	$(PYTHON) $(WORKFLOW) check

unit:
	$(PYTHON) $(WORKFLOW) unit

fact:
	$(PYTHON) $(WORKFLOW) fact

smoke:
	$(PYTHON) $(WORKFLOW) smoke --scenario server-check

acceptance:
	$(PYTHON) $(WORKFLOW) acceptance

e2e:
	$(PYTHON) $(WORKFLOW) smoke --scenario scenario-ai

server:
	$(PYTHON) $(WORKFLOW) server --version v3

server-v1:
	$(PYTHON) $(WORKFLOW) server --version v1

server-v2:
	$(PYTHON) $(WORKFLOW) server --version v2

server-fast:
	$(PYTHON) $(WORKFLOW) server --version fast --port 8080

manual-ai:
	$(PYTHON) $(WORKFLOW) manual scenario-ai

manual-energy:
	$(PYTHON) $(WORKFLOW) manual scenario-energy

modulation:
	$(PYTHON) $(WORKFLOW) manual modulation

openrouter-setup:
	$(PYTHON) setup_openrouter.py
