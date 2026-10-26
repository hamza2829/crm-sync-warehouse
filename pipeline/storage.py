"""One small DB-API adapter; SQL values are always bound parameters."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import warehouse

SQL_ROOT = Path(warehouse.__file__).parent
TABLES = {"deals": "raw_deals", "companies": "raw_companies", "contacts": "raw_contacts"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def json_text(value) -> str:
    return json.dumps(value, default=str, sort_keys=True)


class Database:
    def __init__(self, url: str | None = None):
        self.url = url or os.getenv("DATABASE_URL", "sqlite:///demo.db")
        self.postgres = self.url.startswith(("postgresql://", "postgres://"))
        if not self.postgres and not self.url.startswith("sqlite:///"):
            raise ValueError("Use a postgresql:// or sqlite:/// database URL")

    @contextmanager
    def connect(self, *, readonly: bool = False):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row

            connection = psycopg.connect(self.url, row_factory=dict_row)
            if readonly:
                connection.read_only = True
        else:
            path = self.url.removeprefix("sqlite:///")
            if readonly:
                connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
                connection.execute("PRAGMA query_only = ON")
            else:
                connection = sqlite3.connect(path)
            connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def execute(self, connection, sql: str, params=()):
        return connection.execute(sql.replace("?", "%s") if self.postgres else sql, params)

    def rows(self, sql: str, params=(), *, readonly: bool = False) -> list[dict]:
        with self.connect(readonly=readonly) as connection:
            return [dict(row) for row in self.execute(connection, sql, params).fetchall()]

    def apply_sql(self, path: Path):
        with self.connect() as connection:
            # Files deliberately contain simple statements without procedural SQL.
            for statement in path.read_text(encoding="utf-8").split(";"):
                if statement.strip():
                    connection.execute(statement)

    def initialize(self):
        self.apply_sql(SQL_ROOT / "001_schema.sql")

    def cursor(self) -> str | None:
        rows = self.rows("SELECT cursor FROM sync_state WHERE resource = ?", ("deals",))
        return rows[0]["cursor"] if rows else None

    def upsert(self, connection, resource: str, parsed: dict, raw: dict):
        table = TABLES[resource]
        # Column names come from our schema models, never from the source payload.
        from pipeline.schemas import SCHEMAS

        columns = list(SCHEMAS[resource].model_fields) + ["raw"]
        values = [parsed[column] for column in columns[:-1]] + [json_text(raw)]
        updates = ", ".join(f"{column}=excluded.{column}" for column in columns if column != "id")
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)}) ON CONFLICT (id) DO UPDATE SET {updates}"
        )
        self.execute(connection, sql, values)
