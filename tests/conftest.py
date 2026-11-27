"""Fixture compartida: base de datos temporal con migraciones aplicadas."""
from __future__ import annotations

import pytest

from app.core.database import Database
from app.core.migrations import run_migrations
from app.core.settings import Settings
from app.signals import SignalBus


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db").connect()
    run_migrations(database, log=lambda msg: None)
    yield database
    database.close()


@pytest.fixture()
def bus():
    return SignalBus()


@pytest.fixture()
def settings(tmp_path):
    return Settings(tmp_path / "config.json")
