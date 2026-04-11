.PHONY: setup dev lint test clean

setup:
	@echo "Installing dependencies..."
	pip install -e ".[dev]"
	@echo "Ensuring Ollama model is available..."
	ollama pull gemma4:e4b
	@echo "Creating data directory..."
	mkdir -p ~/.tifaw
	@echo "Setup complete! Run 'make dev' to start."

dev:
	uvicorn tifaw.main:app --host 127.0.0.1 --port 8321 --reload

lint:
	ruff check tifaw/ tests/
	ruff format --check tifaw/ tests/

format:
	ruff check --fix tifaw/ tests/
	ruff format tifaw/ tests/

test:
	pytest tests/ -v

clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache *.egg-info dist build
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
