VENV := .venv/bin

# ruff: prefer the project venv, fall back to `uvx ruff` when no venv is present
RUFF := $(shell [ -x .venv/bin/ruff ] && echo .venv/bin/ruff || echo "uvx ruff")

.PHONY: test lint fmt typecheck check e2e hooks

# tests/e2e/ is entirely @pytest.mark.e2e (builds+installs a wheel per
# scenario). `test`/`check` deselect it for CI-speed unit/integration runs;
# `e2e` targets the same tree with no marker filter to run it on its own.
# `.github/workflows/publish.yml` also runs `make e2e` automatically on every
# release-tag push, before publishing; run it locally first too (see
# docs/development/release-sandbox.md) so a failure surfaces before tagging.
test:
	$(VENV)/pytest tests/ -v -m "not e2e"

lint:
	$(RUFF) check src/ tests/

fmt:
	$(RUFF) format src/ tests/

typecheck:
	$(VENV)/pyright src/

check: lint typecheck test

e2e:
	$(VENV)/pytest tests/e2e/ -v

hooks:
	@echo '#!/bin/sh\nmake check' > .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "pre-commit hook installed: runs make check before every commit"
