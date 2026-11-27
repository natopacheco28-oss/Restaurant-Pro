"""Pruebas de base de datos y migraciones versionadas."""
from __future__ import annotations

import pytest

from app.core.database import Database
from app.core.migrations import run_migrations


def test_migrations_create_schema(db):
    tables = {row["name"] for row in db.query(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    expected = {"categories", "products", "ingredients", "recipes",
                "cash_sessions", "sales", "sale_items", "movements"}
    assert expected.issubset(tables)
    assert db.user_version() == 1


def test_migrations_are_idempotent(db):
    assert run_migrations(db, log=lambda msg: None) == db.user_version()


def test_fresh_database_version(tmp_path):
    database = Database(tmp_path / "fresh.db").connect()
    assert database.user_version() == 0
    run_migrations(database, log=lambda msg: None)
    assert database.user_version() == 1
    database.close()


def test_transaction_rollback(db):
    db.execute("INSERT INTO categories (name) VALUES ('Segura')")
    with pytest.raises(Exception):
        with db.transaction():
            db.execute("INSERT INTO categories (name) VALUES ('A')")
            raise RuntimeError("fallo simulado")
    names = [row["name"] for row in db.query("SELECT name FROM categories")]
    assert names == ["Segura"]
