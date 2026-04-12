VENV := .venv/bin

.PHONY: setup dev app lint test clean

setup:
	@echo "Installing dependencies..."
	$(VENV)/pip install -e ".[dev]"
	@echo "Ensuring Ollama model is available..."
	ollama pull gemma4:e4b
	@echo "Creating data directory..."
	mkdir -p ~/.tifaw
	@echo "Setup complete! Run 'make dev' to start."

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

clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache *.egg-info dist build
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
