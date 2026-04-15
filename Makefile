VENV := .venv/bin
GREEN := \033[32m
RED := \033[31m
YELLOW := \033[33m
RESET := \033[0m
PASS := $(GREEN)✓$(RESET)
FAIL := $(RED)✗$(RESET)
WARN := $(YELLOW)!$(RESET)

.PHONY: check setup doctor dev app lint format test build build-zip build-dmg clean

check:
	@echo "Checking prerequisites..."
	@OK=1; \
	PY_VER=$$(python3 --version 2>/dev/null | awk '{print $$2}'); \
	if [ -z "$$PY_VER" ]; then \
		printf "  $(FAIL) Python 3.11+ — not found (https://python.org)\n"; OK=0; \
	else \
		PY_MAJOR=$$(echo "$$PY_VER" | cut -d. -f1); \
		PY_MINOR=$$(echo "$$PY_VER" | cut -d. -f2); \
		if [ "$$PY_MAJOR" -ge 3 ] && [ "$$PY_MINOR" -ge 11 ]; then \
			printf "  $(PASS) Python $$PY_VER\n"; \
		else \
			printf "  $(FAIL) Python 3.11+ — found $$PY_VER (upgrade at https://python.org)\n"; OK=0; \
		fi; \
	fi; \
	if command -v ollama >/dev/null 2>&1; then \
		printf "  $(PASS) Ollama installed\n"; \
		if curl -s -o /dev/null -w '' http://localhost:11434/api/tags 2>/dev/null; then \
			printf "  $(PASS) Ollama running\n"; \
		else \
			printf "  $(WARN) Ollama installed but not running — start with: open -a Ollama\n"; \
		fi; \
	else \
		printf "  $(FAIL) Ollama not installed — download from https://ollama.com\n"; OK=0; \
	fi; \
	AVAIL=$$(df -g ~ 2>/dev/null | tail -1 | awk '{print $$4}'); \
	if [ -n "$$AVAIL" ] && [ "$$AVAIL" -lt 6 ] 2>/dev/null; then \
		printf "  $(WARN) Low disk space ($${AVAIL}GB free) — Gemma 4 needs ~5GB\n"; \
	fi; \
	if [ "$$OK" = "0" ]; then \
		echo ""; printf "$(RED)Fix the issues above before running setup.$(RESET)\n"; exit 1; \
	fi; \
	echo ""; echo "All prerequisites met."

setup: check
	@echo "Installing dependencies..."
	$(VENV)/pip install -e ".[dev]"
	@echo "Ensuring Ollama model is available..."
	ollama pull gemma4:e4b
	@echo "Creating data directory..."
	mkdir -p ~/.tifaw
	@echo ""
	@$(MAKE) --no-print-directory doctor

doctor:
	@echo "Running health checks..."
	@PASSED=0; TOTAL=6; \
	if $(VENV)/python -c "import tifaw" 2>/dev/null; then \
		printf "  $(PASS) Python package installed\n"; PASSED=$$((PASSED+1)); \
	else \
		printf "  $(FAIL) Python package — run: $(VENV)/pip install -e \".[dev]\"\n"; \
	fi; \
	if curl -s -o /dev/null -w '' http://localhost:11434/api/tags 2>/dev/null; then \
		printf "  $(PASS) Ollama reachable\n"; PASSED=$$((PASSED+1)); \
	else \
		printf "  $(FAIL) Ollama not reachable — start with: open -a Ollama\n"; \
	fi; \
	if ollama list 2>/dev/null | grep -q "gemma4"; then \
		printf "  $(PASS) Gemma 4 model pulled\n"; PASSED=$$((PASSED+1)); \
	else \
		printf "  $(FAIL) Model not found — run: ollama pull gemma4:e4b\n"; \
	fi; \
	if [ -d "$$HOME/.tifaw" ]; then \
		printf "  $(PASS) Data directory (~/.tifaw)\n"; PASSED=$$((PASSED+1)); \
	else \
		printf "  $(FAIL) Data directory missing — run: mkdir -p ~/.tifaw\n"; \
	fi; \
	if [ -f "config.yaml" ]; then \
		printf "  $(PASS) config.yaml exists\n"; PASSED=$$((PASSED+1)); \
	else \
		printf "  $(FAIL) config.yaml missing — app will use defaults\n"; \
	fi; \
	if $(VENV)/python -c "from tifaw.config import load_settings; s = load_settings(); print('  $(PASS) Settings load OK (' + str(s.db_path) + ')')" 2>/dev/null; then \
		PASSED=$$((PASSED+1)); \
	else \
		printf "  $(FAIL) Settings failed to load\n"; \
	fi; \
	echo ""; \
	if [ "$$PASSED" -eq "$$TOTAL" ]; then \
		printf "$(GREEN)$$PASSED/$$TOTAL checks passed. Run 'make dev' to start!$(RESET)\n"; \
	else \
		printf "$(YELLOW)$$PASSED/$$TOTAL checks passed. Fix issues above and re-run 'make doctor'.$(RESET)\n"; \
	fi

dev:
	$(VENV)/uvicorn tifaw.main:app --host 127.0.0.1 --port 8321 --reload

app:
	$(VENV)/python -m tifaw.app

lint:
	$(VENV)/ruff check tifaw/ tests/
	$(VENV)/ruff format --check tifaw/ tests/

format:
	$(VENV)/ruff check --fix tifaw/ tests/
	$(VENV)/ruff format tifaw/ tests/

test:
	$(VENV)/pytest tests/ -v

build:
	@echo "Building Tifaw.app..."
	$(VENV)/pip install pyinstaller
	$(VENV)/pyinstaller Tifaw.spec --noconfirm
	@echo ""
	@echo "$(GREEN)Built: dist/Tifaw.app$(RESET)"

build-zip: build
	cd dist && zip -r Tifaw-macos.zip Tifaw.app
	@echo "$(GREEN)Package: dist/Tifaw-macos.zip$(RESET)"

build-dmg: build
	@echo "Creating Tifaw.dmg..."
	hdiutil create -volname "Tifaw" -srcfolder dist/Tifaw.app -ov -format UDZO dist/Tifaw.dmg
	@echo "$(GREEN)Package: dist/Tifaw.dmg$(RESET)"

clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache *.egg-info dist build
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
