"""Acceso a la base de datos SQLite de Restaurante Pro.

Una única conexión con helpers de consulta, transacciones explícitas y
PRAGMA de integridad (claves foráneas + WAL para resistencia a cortes de
energía, algo crítico en una caja de restaurante).
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    """Envoltura ligera sobre sqlite3 con API cómoda para la app."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------

    def connect(self) -> "Database":
        """Abre la conexión y aplica los PRAGMA de integridad."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            # Autocommit manual: las transacciones se controlan con
            # `transaction()` para que venta + inventario sean atómicas.
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        return self

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def reopen(self) -> None:
        """Cierra y vuelve a abrir (usado tras restaurar un respaldo)."""
        with self._lock:
            self.close()
            self.connect()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("La base de datos no está abierta; llama a connect().")
        return self._conn

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Ejecuta un SELECT y devuelve filas como diccionarios."""
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def one(self, sql: str, params: tuple = ()) -> dict | None:
        """Ejecuta un SELECT y devuelve la primera fila (o None)."""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Ejecuta INSERT/UPDATE/DELETE y devuelve el último rowid."""
        with self._lock:
            cur = self.conn.execute(sql, params)
            return int(cur.lastrowid or 0)

    def execute_many(self, sql: str, seq: list[tuple]) -> None:
        with self._lock:
            self.conn.executemany(sql, seq)

    def execute_script(self, sql_script: str) -> None:
        with self._lock:
            self.conn.executescript(sql_script)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Transacción explícita (todo o nada).

        Ejemplo:
            with db.transaction():
                db.execute("INSERT ...")
                db.execute("UPDATE ...")
        """
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    # ------------------------------------------------------------------
    # Versión de esquema (migraciones)
    # ------------------------------------------------------------------

    def user_version(self) -> int:
        """Versión actual del esquema guardada en PRAGMA user_version."""
        row = self.conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def set_user_version(self, version: int) -> None:
        self.conn.execute(f"PRAGMA user_version = {int(version)}")
