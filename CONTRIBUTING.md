# Contributing to Reddit Options Trader (ROT)

Thank you for your interest in contributing! This document explains how to get
the project running locally, run tests, and submit pull requests.

---

## Prerequisites

- **Python 3.10+** (3.11 or 3.12 recommended for best type-checking support)
- **Redis** running locally on `localhost:6379` (used by deduplication and
  caching layers; most unit tests mock this away, but integration tests use it)
- **Git** 2.30+
- **Docker** (optional — for running the full stack via `docker-compose up`)

### Required environment variables

Copy the example env file and fill in your keys:

```bash
cp .env.example .env
```

Key variables:

| Variable | Description |
|---|---|
| `REDDIT_CLIENT_ID` | Reddit OAuth app client ID |
| `REDDIT_CLIENT_SECRET` | Reddit OAuth app client secret |
| `OPENAI_API_KEY` | OpenAI API key for LLM enrichment |
| `ANTHROPIC_API_KEY` | Anthropic API key (Claude) |
| `STRIPE_SECRET_KEY` | Stripe secret key (billing) |
| `SECRET_KEY` | JWT signing secret (generate with `openssl rand -hex 32`) |
| `DATABASE_URL` | SQLite or Postgres URL (default: `sqlite+aiosqlite:///rot.db`) |

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/Mattbusel/Reddit-Options-Trader-ROT-.git
cd Reddit-Options-Trader-ROT-

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install the package in editable mode with all dev dependencies
pip install -e ".[dev]"
```

---

## Running Tests

```bash
# Run the full test suite (parallel via pytest-xdist)
pytest -n auto

# Run with coverage report
pytest --cov=rot --cov-report=term-missing

# Run a specific file
pytest tests/test_nlp_engine.py -v

# Run only integration tests
pytest tests/ -k "integration" -v
```

The CI gate requires **75% coverage** — please maintain or improve this
threshold when adding new code.

---

## Code Style

ROT enforces **ruff** for linting/formatting and **mypy** for type checking.

```bash
# Lint
ruff check src/ tests/

# Format (in-place)
ruff format src/ tests/

# Check formatting without changing files
ruff format --check src/ tests/

# Type checking
mypy src/rot/core/ src/rot/app/ src/rot/backtest/ src/rot/flow/ src/rot/strategy/
```

All public functions and classes must have type annotations. Run mypy locally
before pushing — the CI gate will fail on type errors.

---

## Submitting a Pull Request

1. Fork the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Make your changes, add tests, and ensure `pytest` and `ruff check` pass
   locally.
3. Commit with a descriptive message following
   [Conventional Commits](https://www.conventionalcommits.org/) style
   (e.g. `feat: add gamma-weighted flow scoring`).
4. Push your branch and open a PR against `main`.
5. Fill in the PR template — describe what changed, why, and how you tested it.
6. A maintainer will review within a few business days. Please be responsive to
   review comments.

### PR checklist

- [ ] Tests added or updated
- [ ] `ruff check` passes with no errors
- [ ] `mypy` passes with no new errors
- [ ] Coverage not reduced below 75%
- [ ] Docstrings added to all new public modules, classes, and functions
- [ ] `CHANGELOG.md` updated if the change is user-facing

---

## Questions?

Open a [GitHub Discussion](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-/discussions)
or file an issue if something is unclear. We welcome contributions of all sizes.
