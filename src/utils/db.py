"""Shared Postgres connection helper.

Pooled, because the database is a hosted Supabase instance and every
`psycopg2.connect()` pays a full TCP + TLS + pooler handshake across the
network. Measured against the live database, that handshake dominated
everything else: one match made ~7 connections and took 39 seconds, of
which roughly 35 was connecting. Ranking one resume against 13 postings
took 8 minutes. The same work on a pooled connection is a few seconds.

The call sites are unchanged -- `get_connection()` then `conn.close()`.
The object handed back is a proxy whose `close()` returns the connection
to the pool instead of dropping it.
"""
import os
import threading
import time
from contextlib import contextmanager

import psycopg2
from dotenv import load_dotenv
from psycopg2 import pool as psycopg2_pool

load_dotenv()

MIN_CONNECTIONS = 1
MAX_CONNECTIONS = 12
# A leaked connection (one whose caller raised before close()) used to
# take the pool down with "connection pool exhausted" on the next few
# requests. Two defences: PooledConnection.__del__ returns anything the
# garbage collector reclaims, and getconn waits for a free slot instead
# of failing instantly, since contention here is brief.
ACQUIRE_TIMEOUT_SECONDS = 15.0
ACQUIRE_RETRY_SECONDS = 0.1

_pool = None
_pool_lock = threading.Lock()


def _database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set – check your .env file.")
    return database_url


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = psycopg2_pool.ThreadedConnectionPool(
                MIN_CONNECTIONS, MAX_CONNECTIONS, _database_url()
            )
        return _pool


class PooledConnection:
    """Proxies a pooled psycopg2 connection; close() returns it to the pool.

    Everything else (cursor, commit, rollback, autocommit, …) passes
    straight through, so existing code needs no changes.
    """

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._returned = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        if self._returned:
            return
        self._returned = True
        # A connection that errored mid-transaction would poison the next
        # user of it, so roll back before it goes back in the pool, and
        # discard it outright if it is already broken.
        try:
            if self._conn.closed:
                self._pool.putconn(self._conn, close=True)
                return
            self._conn.rollback()
        except psycopg2.Error:
            self._pool.putconn(self._conn, close=True)
            return
        self._pool.putconn(self._conn)

    def __del__(self):
        # safety net for a caller that raised before close(); without it
        # the slot is lost for the life of the process
        try:
            self.close()
        except Exception:  # noqa: BLE001 -- nothing useful to do in __del__
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def get_connection() -> PooledConnection:
    pool = _get_pool()
    deadline = time.monotonic() + ACQUIRE_TIMEOUT_SECONDS
    while True:
        try:
            conn = pool.getconn()
            break
        except psycopg2_pool.PoolError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(ACQUIRE_RETRY_SECONDS)

    if conn.closed:
        # the pooler drops idle connections; swap a dead one out rather
        # than handing it to the caller
        pool.putconn(conn, close=True)
        conn = pool.getconn()
    return PooledConnection(conn, pool)


@contextmanager
def connection():
    """Preferred form: returns the connection even when the body raises."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def close_all_connections() -> None:
    """Drop the whole pool. For tests and shutdown hooks."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.closeall()
            _pool = None
