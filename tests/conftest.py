import pytest
from app import app as flask_app
from database.db import get_db, init_db


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    monkeypatch.setitem(flask_app.config, "DATABASE", str(tmp_path / "expenses.db"))
    monkeypatch.setitem(flask_app.config, "SECRET_KEY", "test-secret")
    with flask_app.app_context():
        init_db()
    return flask_app


@pytest.fixture
def db(app):
    with app.app_context():
        yield get_db()
