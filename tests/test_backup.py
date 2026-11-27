"""Pruebas del gestor de respaldos."""
from __future__ import annotations

import os
import sqlite3

import pytest

from app.core.backup import BackupManager


# ------------------------------------------------------------------
# Utilidades: bases de datos reales (el restore valida que sean SQLite)
# ------------------------------------------------------------------

def make_db(path, value: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('contenido', ?)", (value,))
    conn.commit()
    conn.close()


def read_db(path) -> str:
    conn = sqlite3.connect(path)
    value = conn.execute("SELECT v FROM meta WHERE k = 'contenido'").fetchone()[0]
    conn.close()
    return value


@pytest.fixture()
def backup_env(tmp_path):
    db_file = tmp_path / "restaurante.db"
    make_db(db_file, "contenido-original")
    backups_dir = tmp_path / "backups"
    manager = BackupManager(db_path=lambda: db_file, backup_dir=lambda: backups_dir)
    return manager, db_file, backups_dir


def test_backup_now_creates_dated_file(backup_env):
    manager, db_file, backups_dir = backup_env
    backup = manager.backup_now("manual")
    assert backup.exists()
    assert backup.name.startswith("backup_")
    assert "manual" in backup.name
    assert read_db(backup) == "contenido-original"


def test_prune_keeps_last_ten(backup_env):
    manager, _, _ = backup_env
    for index in range(12):
        backup = manager.backup_now("auto")
        # mtimes distintos para ordenar de forma determinista
        os.utime(backup, (1700000000 + index * 60, 1700000000 + index * 60))
    assert len(manager.list_backups()) == 10


def test_list_backups_ordered_desc(backup_env):
    manager, _, _ = backup_env
    first = manager.backup_now("a")
    os.utime(first, (1700000000, 1700000000))
    second = manager.backup_now("b")
    os.utime(second, (1700000600, 1700000600))
    backups = manager.list_backups()
    assert backups[0] == second   # el más reciente primero
    assert backups[-1] == first


def test_restore_replaces_database_and_keeps_pre_copy(backup_env):
    manager, db_file, _ = backup_env
    backup = manager.backup_now("punto")
    make_db(db_file, "contenido-nuevo")

    pre_restore = manager.restore(backup)
    assert pre_restore.exists()                                  # copia previa
    assert read_db(pre_restore) == "contenido-nuevo"             # guardó lo previo
    assert read_db(db_file) == "contenido-original"              # respaldo aplicado


def test_restore_rejects_invalid_sqlite(tmp_path):
    db_file = tmp_path / "restaurante.db"
    make_db(db_file, "x")
    bad = tmp_path / "backup_bad.db"
    bad.write_bytes(b"no es sqlite")
    manager = BackupManager(db_path=lambda: db_file, backup_dir=lambda: tmp_path / "b")
    with pytest.raises(ValueError):
        manager.restore(bad)


def test_backup_missing_db_raises(tmp_path):
    manager = BackupManager(
        db_path=lambda: tmp_path / "inexistente.db",
        backup_dir=lambda: tmp_path / "b",
    )
    with pytest.raises(FileNotFoundError):
        manager.backup_now()
