"""Provision isolated API fixtures explicitly; production startup never migrates."""
from relay.migrations import MigrationService, create_backup

TEST_PASSWORD = "test-only long password"


def prepare(store, directory):
    store.seed()
    MigrationService(store.database, directory).apply(
        create_backup(store.database, directory, quiesced=True))


def login(client):
    result = client.post("/api/auth/login", json={"username": "owner", "password": TEST_PASSWORD})
    assert result.status_code == 200, result.text
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return result.json()
