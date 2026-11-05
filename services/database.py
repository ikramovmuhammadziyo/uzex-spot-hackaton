"""Read-only DuckDB access for the bot.

The database is built by ``utils/db_api/load_data.py``.  The bot opens it in
read-only mode, serialises access with a lock, and interrupts queries that run
longer than the configured budget.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from data import config


class DatabaseError(RuntimeError):
    """A database problem that can be shown to the user in a generic form."""


@dataclass(slots=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)


class Database:
    def __init__(self, path: Path | str = config.DB_PATH) -> None:
        self.path = Path(path)
        self._connection: Any | None = None
        self._lock = threading.Lock()
        self._error: str | None = None
        self._generation: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._connection is not None

    @property
    def last_error(self) -> str | None:
        return self._error

    def connect(self) -> None:
        if self._connection is not None:
            return
        if not self.path.is_file():
            self._error = f"database file not found: {self.path}"
            raise DatabaseError(
                f"{self._error}. Build it with: python utils/db_api/load_data.py"
            )
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - dependency problem
            self._error = "duckdb is not installed"
            raise DatabaseError("duckdb is not installed: pip install duckdb") from exc

        try:
            connection = duckdb.connect(str(self.path), read_only=True)
            connection.execute("PRAGMA threads=4")
            # A runaway query should fail instead of eating all RAM.
            try:
                connection.execute("PRAGMA memory_limit='2GB'")
            except Exception:
                pass
            self._generation = self._file_generation()
            self._connection = connection
            self._error = None
        except Exception as exc:
            self._error = str(exc)
            raise DatabaseError(f"cannot open {self.path}: {exc}") from exc

    def _file_generation(self) -> str:
        stat = self.path.stat()
        return f"{self.path.resolve()}:{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}"

    @property
    def dataset_version(self) -> str:
        if not self.available:
            raise DatabaseError("database is not connected")
        try:
            current = self._file_generation()
        except OSError as exc:
            raise DatabaseError("database snapshot is unavailable; reconnect required") from exc
        if current != self._generation:
            raise DatabaseError("database snapshot changed; reconnect required")
        return current

    def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception:  # pragma: no cover - best effort
                pass

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    async def query(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
        *,
        max_rows: int = config.SQL_MAX_ROWS,
        timeout: float = config.SQL_TIMEOUT_SECONDS,
    ) -> QueryResult:
        if self._connection is None:
            raise DatabaseError(self._error or "database is not connected")

        self.dataset_version  # reject replacement of the connected immutable snapshot
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, self._execute, sql, params, max_rows)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self.interrupt()
            raise DatabaseError(f"query timed out after {timeout:.0f}s") from None

    def _execute(
        self,
        sql: str,
        params: Sequence[Any] | None,
        max_rows: int,
    ) -> QueryResult:
        with self._lock:
            if self._connection is None:
                raise DatabaseError("database is not connected")
            cursor = self._connection.cursor()
            try:
                cursor.execute(sql, list(params) if params else [])
                columns = [item[0] for item in cursor.description] if cursor.description else []
                rows = cursor.fetchmany(max_rows + 1) if columns else []
                truncated = len(rows) > max_rows
                return QueryResult(
                    columns=columns,
                    rows=[list(row) for row in rows[:max_rows]],
                    truncated=truncated,
                )
            except Exception as exc:
                raise DatabaseError(str(exc)) from exc
            finally:
                try:
                    cursor.close()
                except Exception:  # pragma: no cover - best effort
                    pass

    def interrupt(self) -> None:
        connection = self._connection
        if connection is None:
            return
        try:
            connection.interrupt()
        except Exception:  # pragma: no cover - best effort
            pass

    # ------------------------------------------------------------------
    # Health / metadata
    # ------------------------------------------------------------------
    async def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in ("deals", "contracts", "participants", "brokers", "usd_rates"):
            result = await self.query(f"SELECT COUNT(*) FROM {table}", max_rows=1)
            counts[table] = int(result.rows[0][0]) if result.rows else 0
        return counts

    async def ping(self) -> bool:
        try:
            await self.query("SELECT 1", max_rows=1, timeout=5)
            return True
        except DatabaseError:
            return False

    def file_size_mb(self) -> float:
        try:
            return self.path.stat().st_size / (1024 * 1024)
        except OSError:
            return 0.0
