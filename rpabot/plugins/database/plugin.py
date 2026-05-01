"""Database plugin for the RPA framework.

Provides database access via SQLAlchemy, integrated with the framework's
plugin lifecycle.  Supports SQLite, MySQL, PostgreSQL, and any SQLAlchemy-
compatible backend.

Usage::

    from rpabot.plugins.database.plugin import DatabasePlugin
    from rpabot.plugin.base import PluginManager

    mgr = PluginManager(context)
    db = DatabasePlugin("sqlite:///app.db")
    mgr.register(db)
    mgr.start_all()

    users = db.execute("SELECT * FROM users WHERE status = :s", {"s": "active"})
    db.insert("users", {"name": "Alice", "email": "alice@example.com"})
    mgr.shutdown_all()
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Sequence

from sqlalchemy import (
    create_engine,
    Engine,
    MetaData,
    Table,
    text,
    inspect,
    CursorResult,
)
from sqlalchemy.orm import Session

from rpabot.plugin.base import Plugin

logger = logging.getLogger("rpa.database")


class DatabasePlugin:
    """Plugin for database operations via SQLAlchemy.

    Attributes:
        name: Plugin identifier (``"database"``).
        url: Database connection URL (e.g. ``sqlite:///data.db``).
    """

    name = "database"

    def __init__(self, url: Optional[str] = None, *, echo: bool = False) -> None:
        self._url = url
        self._echo = echo
        self._engine: Optional[Engine] = None
        self._session: Optional[Session] = None
        self._metadata: Optional[MetaData] = None
        self._context: Any = None

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def initialize(self, context: Any) -> None:
        self._context = context
        if self._url:
            self.connect(self._url)
        logger.info("DatabasePlugin initialized")

    def cleanup(self) -> None:
        self.disconnect()
        logger.info("DatabasePlugin cleaned up")

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self, url: str, *, echo: bool = False) -> None:
        """Connect to a database.

        Args:
            url: SQLAlchemy connection URL.
            echo: If True, log all SQL statements.
        """
        if self._engine:
            self.disconnect()

        self._url = url
        self._echo = echo
        self._engine = create_engine(url, echo=echo)
        self._session = Session(self._engine)
        self._metadata = MetaData()
        self._metadata.reflect(bind=self._engine)
        logger.info("Connected to database: %s", self._mask_url(url))

    def disconnect(self) -> None:
        """Close the current connection."""
        if self._session:
            self._session.close()
            self._session = None
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._metadata = None
            logger.info("Database disconnected")

    @property
    def engine(self) -> Engine:
        """The SQLAlchemy :class:`Engine`."""
        if self._engine is None:
            raise RuntimeError("DatabasePlugin not connected. Call connect() first.")
        return self._engine

    @property
    def session(self) -> Session:
        """The SQLAlchemy :class:`Session`."""
        if self._session is None:
            raise RuntimeError("DatabasePlugin not connected.")
        return self._session

    # ------------------------------------------------------------------
    # Raw SQL
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> CursorResult:
        """Execute a raw SQL statement.

        Args:
            sql: SQL string (use ``:param`` style placeholders).
            params: Dict of parameter bindings.

        Returns:
            A :class:`CursorResult`.
        """
        logger.debug("SQL: %s", sql.strip()[:120])
        return self.session.execute(text(sql), params or {})

    def fetch_all(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results as list of dicts.

        Usage::

            rows = db.fetch_all("SELECT id, name FROM users WHERE status = :s", {"s": "active"})
            # → [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        """
        result = self.execute(sql, params)
        columns = result.keys()
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def fetch_one(self, sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Like :meth:`fetch_all` but returns the first row only (or None)."""
        result = self.execute(sql, params)
        row = result.fetchone()
        if row is None:
            return None
        return dict(zip(result.keys(), row))

    def fetch_scalar(self, sql: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Execute a query and return a single scalar value."""
        result = self.execute(sql, params)
        row = result.fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Table-level operations (auto-reflection)
    # ------------------------------------------------------------------

    def _get_table(self, table_name: str) -> Table:
        """Get a reflected table by name.  Auto-reflects if not yet loaded."""
        if self._metadata is None:
            raise RuntimeError("DatabasePlugin not connected.")
        if table_name not in self._metadata.tables:
            self._metadata.reflect(bind=self._engine, only=[table_name])
        return self._metadata.tables[table_name]

    def list_tables(self) -> List[str]:
        """Return names of all tables in the database."""
        insp = inspect(self.engine)
        return insp.get_table_names()

    def list_columns(self, table_name: str) -> List[Dict[str, Any]]:
        """Return column metadata for a table."""
        insp = inspect(self.engine)
        return insp.get_columns(table_name)

    def insert(self, table_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a row and return it as a dict (including generated columns).

        Usage::

            row = db.insert("users", {"name": "Alice", "email": "a@b.com"})
        """
        table = self._get_table(table_name)
        stmt = table.insert().values(**data)
        result = self.session.execute(stmt)
        self.session.flush()
        # Fetch the inserted row using the lastrowid
        pk_cols = [c.name for c in table.primary_key.columns]
        if pk_cols and result.inserted_primary_key:
            pk_vals = dict(zip(pk_cols, result.inserted_primary_key))
            return self.fetch_one(f"SELECT * FROM {table_name} WHERE " +
                " AND ".join(f"{c} = :{c}" for c in pk_cols), pk_vals) or data
        return data

    def update(
        self,
        table_name: str,
        filters: Dict[str, Any],
        data: Dict[str, Any],
    ) -> int:
        """Update rows matching *filters*.  Returns count of affected rows.

        Usage::

            db.update("users", {"id": 1}, {"status": "inactive"})
        """
        table = self._get_table(table_name)
        where_clause = [getattr(table.c, k) == v for k, v in filters.items()]
        from sqlalchemy import and_
        stmt = table.update().where(and_(*where_clause)).values(**data)
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

    def delete(self, table_name: str, **filters: Any) -> int:
        """Delete rows matching *filters*.  Returns count of deleted rows.

        Usage::

            db.delete("users", id=1)
        """
        table = self._get_table(table_name)
        where_clause = [getattr(table.c, k) == v for k, v in filters.items()]
        from sqlalchemy import and_
        stmt = table.delete().where(and_(*where_clause))
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

    def query(self, table_name: str, **filters: Any) -> List[Dict[str, Any]]:
        """Simple query by column equality.

        Usage::

            rows = db.query("users", status="active")
        """
        table = self._get_table(table_name)
        where_clause = [getattr(table.c, k) == v for k, v in filters.items()]
        from sqlalchemy import and_, select

        stmt = select(table)
        if where_clause:
            stmt = stmt.where(and_(*where_clause))
        result = self.session.execute(stmt)
        columns = result.keys()
        return [dict(zip(columns, row)) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Transaction support
    # ------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Generator[Session, None, None]:
        """Context manager that wraps operations in a transaction.

        On exit, commits if no exception occurred, otherwise rolls back.
        Uses SAVEPOINT so nested invocations are safe.

        Usage::

            with db.transaction():
                db.insert("users", {"name": "Alice"})
                db.insert("logs", {"event": "user_created"})
        """
        # begin_nested uses SAVEPOINT — works even when a transaction
        # is already in progress (SQLAlchemy autobegin).
        trans = self.session.begin_nested()
        try:
            yield self.session
            trans.commit()
        except Exception:
            trans.rollback()
            raise

    def commit(self) -> None:
        """Manually commit the current transaction."""
        self.session.commit()

    def rollback(self) -> None:
        """Manually roll back the current transaction."""
        self.session.rollback()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mask_url(url: str) -> str:
        """Hide password in URL for logging."""
        import re
        return re.sub(r"://[^:]+:[^@]+@", "://***:***@", url)
