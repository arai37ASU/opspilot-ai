"""Database connection settings.

Connection details come from environment variables, loaded from .env when
present, so no credentials live in code. The same .env file configures the
Docker container (compose.yaml) and the Python code.
"""

import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def database_url(variable: str = "DATABASE_URL") -> str:
    url = os.environ.get(variable)
    if not url:
        raise RuntimeError(f"{variable} is not set. Copy .env.example to .env and fill it in.")
    return url


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or database_url())
