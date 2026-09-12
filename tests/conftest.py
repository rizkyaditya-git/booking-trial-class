import pytest

from app.db.connection import setup_database


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.sqlite3"
    setup_database(path)
    return path


@pytest.fixture
def app(db_path):
    from app.main import create_app

    return create_app(db_path)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, follow_redirects=False) as client:
        yield client
