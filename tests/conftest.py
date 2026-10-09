import pytest

from app import create_app
from app.extensions import db


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def register(client, name, email):
    return client.post(
        "/register",
        data={"name": name, "email": email, "password": "correct-horse-battery"},
        follow_redirects=True,
    )


@pytest.fixture()
def register_user():
    return register
