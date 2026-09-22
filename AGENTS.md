# Repository Guidelines

## Project Structure & Module Organization

Spendly is a Flask expense-tracker starter application. `app.py` defines routes and starts the development server. `templates/` contains Jinja2 pages; extend `base.html` for shared navigation, footer, and asset links. Keep styles in `static/css/style.css` and browser behavior in `static/js/main.js`.

`database/db.py` is a placeholder for SQLite connection, schema initialization, and seed helpers; `database/__init__.py` marks the package. Authentication forms currently only render, and profile, logout, and expense routes are placeholders. No tests directory exists yet; add tests under `tests/` as behavior is implemented.

## Build, Test, and Development Commands

Run commands from the repository root:

```sh
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
venv/bin/python app.py
venv/bin/python -m pytest
```

These create the virtual environment, install pinned dependencies, start Flask at `http://127.0.0.1:5001`, and run tests, respectively. Using the explicit interpreter avoids relying on shell activation. There is no separate build step. Until tests are added, pytest will report no tests collected.

## Coding Style & Naming Conventions

Use four-space indentation in Python, HTML, and CSS, matching existing files. Use `snake_case` for Python functions and modules, and descriptive hyphenated CSS classes such as `auth-card`. Keep database operations in `database/db.py` and request handling in `app.py`. Reuse Jinja blocks and existing CSS variables. Prefer `url_for()` for template links. No formatter or linter is currently configured; keep changes consistent with surrounding code.

## Testing Guidelines

Dependencies include pytest and pytest-flask. Name files `tests/test_*.py` and functions `test_*`; place shared fixtures in `tests/conftest.py`. Test route responses, form validation, authentication, and expense persistence as implemented. Use isolated temporary databases for database tests. No coverage threshold is configured. For template or styling changes, also check affected pages in a browser.

## Commit & Pull Request Guidelines

History currently contains only `initial commit`, so no established message convention exists. Write concise, action-oriented subjects, such as `Add registration validation`, and keep commits focused. Pull requests should describe changed behavior, include validation results, link relevant issues, and provide screenshots for visible interface changes.

## Security & Configuration

Keep credentials, `.env`, `venv/`, and `expense_tracker.db` out of commits, consistent with `.gitignore`. The current server enables debug mode; use it only for local development.
