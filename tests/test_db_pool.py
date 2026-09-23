"""
Pooled connection proxy. Fake pool and connection, so no database.

The point of the proxy is that existing call sites still say
conn.close(), but the connection goes back to the pool instead of being
dropped -- connecting to the hosted database costs far more than any
query it then runs.
"""
from __future__ import annotations

import psycopg2
import pytest

from src.utils.db import PooledConnection


class FakePool:
    def __init__(self):
        self.returned: list[tuple] = []

    def putconn(self, conn, close=False):
        self.returned.append((conn, close))


class FakeConn:
    def __init__(self, closed=0, rollback_error=False):
        self.closed = closed
        self.rollback_error = rollback_error
        self.rolled_back = False

    def rollback(self):
        if self.rollback_error:
            raise psycopg2.OperationalError("connection gone")
        self.rolled_back = True

    def cursor(self):
        return "cursor"


def test_close_returns_the_connection_instead_of_closing_it():
    pool, conn = FakePool(), FakeConn()
    PooledConnection(conn, pool).close()
    assert pool.returned == [(conn, False)]


def test_close_rolls_back_first():
    # a connection left mid-transaction would poison its next user
    pool, conn = FakePool(), FakeConn()
    PooledConnection(conn, pool).close()
    assert conn.rolled_back


def test_a_broken_connection_is_discarded_not_reused():
    pool, conn = FakePool(), FakeConn(rollback_error=True)
    PooledConnection(conn, pool).close()
    assert pool.returned == [(conn, True)]


def test_an_already_closed_connection_is_discarded():
    pool, conn = FakePool(), FakeConn(closed=1)
    PooledConnection(conn, pool).close()
    assert pool.returned == [(conn, True)]


def test_double_close_returns_once():
    pool, conn = FakePool(), FakeConn()
    proxy = PooledConnection(conn, pool)
    proxy.close()
    proxy.close()
    assert len(pool.returned) == 1


def test_attributes_pass_through_to_the_real_connection():
    proxy = PooledConnection(FakeConn(), FakePool())
    assert proxy.cursor() == "cursor"


def test_works_as_a_context_manager():
    pool, conn = FakePool(), FakeConn()
    with PooledConnection(conn, pool) as c:
        assert c.cursor() == "cursor"
    assert pool.returned == [(conn, False)]
