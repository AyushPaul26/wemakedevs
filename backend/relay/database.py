"""Lazy FalkorDB connection shared by legacy and workflow services."""

import os
from threading import Lock

from falkordb import FalkorDB


class GraphDatabase:
    def __init__(self, graph_name: str | None = None):
        self.graph_name = graph_name or os.getenv("RELAY_FALKORDB_GRAPH", "relay_demo")
        self.host = os.getenv("RELAY_FALKORDB_HOST", "127.0.0.1")
        self.port = int(os.getenv("RELAY_FALKORDB_PORT", "6379"))
        self._db = None
        self._graph = None
        self._lock = Lock()

    def _connect(self):
        if self._graph is None:
            with self._lock:
                if self._graph is None:
                    db = FalkorDB(host=self.host, port=self.port,
                                  socket_connect_timeout=3, socket_timeout=10)
                    self._db, self._graph = db, db.select_graph(self.graph_name)

    @property
    def db(self):
        self._connect()
        return self._db

    @property
    def graph(self):
        self._connect()
        return self._graph

    def query(self, statement: str, params: dict | None = None) -> list:
        return self.graph.query(statement, params=params, timeout=5000).result_set

    def read(self, statement: str, params: dict | None = None) -> list:
        return self.graph.ro_query(statement, params=params, timeout=5000).result_set
