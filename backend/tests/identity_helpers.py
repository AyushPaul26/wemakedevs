"""Disposable real-graph fixtures shared by identity and access tests."""

from uuid import uuid4

import pytest
from relay.database import GraphDatabase


@pytest.fixture
def identity_db():
    database = GraphDatabase(graph_name=f"relay_test_{uuid4().hex}")
    database.query("CREATE (:IdentityTestFixture {id:'fixture'})")
    try:
        yield database
    finally:
        assert database.graph_name.startswith("relay_test_")
        database.graph.delete()
