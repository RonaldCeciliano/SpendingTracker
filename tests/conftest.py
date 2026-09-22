import pytest
from flask import Flask

from database.db import get_db, init_app, init_db


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(TESTING=True, DATABASE=str(tmp_path / "expenses.db"))
    init_app(app)
    with app.app_context():
        init_db()
    return app


@pytest.fixture
def db(app):
    with app.app_context():
        yield get_db()
