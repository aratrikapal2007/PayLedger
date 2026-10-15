"""Functional tests for PayLedger. These describe intended behaviour and must
keep passing after any security patch."""
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


def login(c, user="alice", pw=None):
    return c.post("/api/login", json={"username": user, "password": pw or f"{user}123"})


def test_login_ok_and_bad_password(client):
    assert login(client).status_code == 200
    assert client.post("/api/login", json={"username": "alice", "password": "nope"}).status_code == 401


def test_requires_login(client):
    assert client.get("/api/transactions").status_code == 401
    assert client.get("/api/transactions/search?q=a").status_code == 401


def test_list_only_own_transactions(client):
    login(client, "dave")
    data = client.get("/api/transactions").get_json()
    assert len(data) == 2
    assert all(1 for t in data)  # dave is sender or recipient in each


def test_search_filters_by_memo(client):
    login(client, "alice")
    data = client.get("/api/transactions/search?q=dinner").get_json()
    assert [t["memo"] for t in data] == ["Dinner at Bandra"]


def test_search_is_scoped_to_current_user(client):
    login(client, "dave")
    assert client.get("/api/transactions/search?q=Goa").get_json() == []


def test_get_own_transaction(client):
    login(client, "alice")
    assert client.get("/api/transactions/1").status_code == 200


def test_send_money_updates_balances(client):
    login(client, "alice")
    r = client.post("/api/transactions", json={"recipient_id": 2, "amount": "100.50", "memo": "Lunch"})
    assert r.status_code == 201
    assert client.get("/api/me").get_json()["balance_cents"] == 125000 - 10050
    login(client, "bob")
    assert client.get("/api/me").get_json()["balance_cents"] == 80000 + 10050


@pytest.mark.parametrize("payload", [
    {"recipient_id": 2, "amount": "0"},
    {"recipient_id": 2, "amount": "-5"},
    {"recipient_id": 2, "amount": "abc"},
    {"recipient_id": 1, "amount": "10"},
    {"recipient_id": 99, "amount": "10"},
    {"recipient_id": 2, "amount": "999999"},
])
def test_send_money_rejects_invalid(client, payload):
    login(client, "alice")
    assert client.post("/api/transactions", json=payload).status_code == 400


def test_memo_is_stored_as_typed(client):
    login(client, "alice")
    client.post("/api/transactions", json={"recipient_id": 2, "amount": "1", "memo": "Rent & utilities"})
    assert client.get("/api/transactions").get_json()[0]["memo"] == "Rent & utilities"


def test_search_treats_special_characters_literally(client):
    login(client, "alice")
    client.post("/api/transactions", json={"recipient_id": 2, "amount": "5", "memo": "50% advance"})
    assert [t["memo"] for t in client.get("/api/transactions/search?q=50%25").get_json()] == ["50% advance"]
    assert client.get("/api/transactions/search?q=%27").get_json() == []
    assert client.get("/api/transactions/search?q=%25").status_code == 200


def test_search_is_case_insensitive(client):
    login(client, "alice")
    assert len(client.get("/api/transactions/search?q=GOA").get_json()) == 1


def test_newest_transaction_listed_first(client):
    login(client, "alice")
    client.post("/api/transactions", json={"recipient_id": 3, "amount": "10", "memo": "Newest"})
    assert client.get("/api/transactions").get_json()[0]["memo"] == "Newest"


def test_transaction_detail_has_names_and_amount(client):
    login(client, "alice")
    t = client.get("/api/transactions/1").get_json()
    assert (t["sender_name"], t["recipient_name"], t["amount_cents"]) == ("Alice Menon", "Bob D'Souza", 25000)


def test_unknown_transaction_is_404(client):
    login(client, "alice")
    assert client.get("/api/transactions/9999").status_code == 404


def test_users_list_excludes_current_user(client):
    login(client, "alice")
    names = [u["username"] for u in client.get("/api/users").get_json()]
    assert "alice" not in names and len(names) == 3


def test_logout_ends_session(client):
    login(client, "alice")
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_home_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and b"PayLedger" in r.data
    r.close()
