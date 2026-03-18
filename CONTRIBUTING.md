# Contributing

Thanks for contributing.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Development Workflow

1. Create a branch from `main`.
2. Make focused changes with tests.
3. Run:
   - `ruff check .`
   - `pytest`
4. Open a pull request with:
   - what changed,
   - why it changed,
   - how to verify.

## Commit Guidelines

- Use clear, imperative commit messages.
- Keep commits logically scoped.
- Avoid mixing refactors with behavior changes in one commit.

## Data and Privacy

- Do not commit sensitive PDFs or private annotations.
- Redact examples before sharing.

