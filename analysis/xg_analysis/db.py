"""Minimal DB access for MySQL (production) and SQLite (tests, local dev)."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import unquote, urlparse

import pandas as pd

SQLITE_FALLBACK = "sqlite:///xephyguard.sqlite"


def db_url() -> str:
    """XG_DB_URL. Unset or blank is an error, unless XG_ALLOW_SQLITE=1 picks ./xephyguard.sqlite for local
    development: a silent fallback made /health report ok while every /score failed (I-ANALYSIS-23)."""
    url = os.environ.get("XG_DB_URL", "").strip()
    if url:
        return url
    if os.environ.get("XG_ALLOW_SQLITE", "").strip() == "1":
        return SQLITE_FALLBACK
    raise RuntimeError("XG_DB_URL is not set (mysql://user:password@host:3306/db); "
                       "XG_ALLOW_SQLITE=1 uses ./xephyguard.sqlite for local development")


class Db:
    def __init__(self, url: str | None = None):
        self.url = url or db_url()
        u = urlparse(self.url)
        if u.scheme == "sqlite":
            self.kind = "sqlite"
            path = self.url[len("sqlite:///"):] if self.url.startswith("sqlite:///") else u.path
            self.conn = sqlite3.connect(path or ":memory:")
        elif u.scheme in ("mysql", "mysql+pymysql"):
            import pymysql

            self.kind = "mysql"
            self.conn = pymysql.connect(host=u.hostname or "mysql", port=u.port or 3306, user=unquote(u.username or ""),
                                        password=unquote(u.password or ""), database=u.path.lstrip("/"),
                                        charset="utf8mb4", autocommit=False)
        else:
            raise ValueError(f"unsupported database url {self.url!r}")

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.kind == "mysql" else sql

    def df(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), params)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        cur.close()
        return pd.DataFrame(list(rows), columns=cols)

    def one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        d = self.df(sql, params)
        return None if d.empty else d.iloc[0].to_dict()

    def execute(self, sql: str, params: tuple = ()) -> None:
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), params)
        cur.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def ping(self) -> bool:
        try:
            self.df("SELECT 1 AS ok")
            return True
        except Exception:  # noqa: BLE001
            return False


def jload(v: Any) -> Any:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return {}
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return {}
