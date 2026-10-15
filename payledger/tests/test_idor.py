"""Access-control tests: people can only open their own payments."""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as payledger  # noqa: E402


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    payledger.app.config["DATABASE"] = path
    payledger.app.config["TESTING"] = True
    payledger.init_db()
    with payledger.app.test_client() as c:
        yield c
    os.unlink(path)


def login(c, user):
    return c.post("/api/login", json={"username": user, "password": f"{user}123"})


def test_user_cannot_read_someone_elses_transaction(client):
    login(client, "alice")
    # Transaction 5 is Dave -> Bob; Alice is not part of it.
    assert client.get("/api/transactions/5").status_code == 404
    assert client.get("/api/transactions/6").status_code == 404


def test_user_can_still_read_own_transactions(client):
    login(client, "alice")
    for txn_id in (1, 2, 3, 4):
        assert client.get(f"/api/transactions/{txn_id}").status_code == 200


def test_both_parties_can_open_the_same_payment(client):
    login(client, "alice")
    assert client.get("/api/transactions/1").status_code == 200  # sender
    login(client, "bob")
    assert client.get("/api/transactions/1").status_code == 200  # recipient


def test_blocked_and_missing_payments_look_identical(client):
    login(client, "alice")
    blocked = client.get("/api/transactions/5")
    missing = client.get("/api/transactions/9999")
    assert blocked.status_code == missing.status_code == 404
    assert blocked.get_json() == missing.get_json()
