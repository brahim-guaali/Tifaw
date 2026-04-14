# Contributing to Tifaw

Thanks for your interest in contributing! Here's how to get started.

## Prerequisites

- macOS (required for Vision framework and pywebview)
- Python 3.11+
- [Ollama](https://ollama.com) installed and running

## Setup

```bash
git clone https://github.com/brahim-guaali/Tifaw.git
cd Tifaw
make setup
```

This installs dependencies, pulls the Gemma 4 model, and runs health checks.

## Running

```bash
make run      # browser mode at http://localhost:8321
make app      # native macOS window
```

## Development

```bash
make lint     # run ruff linter
make test     # run pytest suite
make check    # verify environment (Python, Ollama, model)
make doctor   # full diagnostic
```

## Code style

- Formatted and linted with [Ruff](https://docs.astral.sh/ruff/)
- Line length: 100
- Target: Python 3.11

## Pull requests

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Run `make lint` and `make test`
4. Open a PR with a clear description of what and why

## Reporting bugs

Use the [bug report template](https://github.com/brahim-guaali/Tifaw/issues/new?template=bug_report.md).

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
