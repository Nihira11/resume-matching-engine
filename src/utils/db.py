"""Shared Postgres connection helper"""
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set – check your .env file.")
    return psycopg2.connect(database_url)
