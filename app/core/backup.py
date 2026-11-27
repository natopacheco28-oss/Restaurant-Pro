"""Respaldos de la base de datos de Restaurante Pro.

- Respaldo automático al cerrar el programa con fecha y hora en el nombre.
- Botón "Respaldar ahora" y "Restaurar respaldo" (con copia previa de la
  base actual antes de restaurar).
- Retención: se conservan los últimos `keep` respaldos.
- Carpeta de respaldos configurable en Ajustes (por defecto `backups/`).
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable


class BackupManager:
    """Crea, lista, podará y restaura respaldos del archivo SQLite."""

    def __init__(
        self,
        db_path: Callable[[], Path],
        backup_dir: Callable[[], Path],
        keep: int = 10,
    ):
        self._db_path = db_path
        self._backup_dir = backup_dir
        self.keep = keep

    # ------------------------------------------------------------------
    # Creación
    # ------------------------------------------------------------------

    def backup_now(self, label: str = "manual") -> Path:
        """Copia la base a `backup_<fecha>_<hora>_<motivo>.db` y poda."""
        src = self._db_path()
        if not src.exists():
            raise FileNotFoundError(f"No existe la base de datos: {src}")

        dest_dir = self._backup_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"backup_{stamp}_{label}.db"
        # Evitar colisiones en el mismo segundo
        counter = 1
        while dest.exists():
            dest = dest_dir / f"backup_{stamp}_{counter}_{label}.db"
            counter += 1

        shutil.copy2(src, dest)
        self.prune()
        return dest

    def prune(self) -> None:
        """Conserva solo los `keep` respaldos más recientes."""
        backups = self.list_backups()
        for old in backups[self.keep:]:
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Consulta / restauración
    # ------------------------------------------------------------------

    def list_backups(self) -> list[Path]:
        """Respaldos disponibles, del más reciente al más antiguo."""
        d = self._backup_dir()
        if not d.exists():
            return []
        return sorted(d.glob("backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)

    def restore(self, backup: Path) -> Path:
        """Restaura un respaldo devolviendo la ruta de la copia previa.

        Antes de sobrescribir se respalda la base actual (por si el usuario
        se arrepiente). El llamador debe cerrar/reabrir la conexión.
        """
        backup = Path(backup)
        if not backup.exists():
            raise FileNotFoundError(f"El respaldo no existe: {backup}")

        # Validación rápida: debe ser un archivo SQLite válido
        try:
            with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as conn:
                conn.execute("PRAGMA schema_version").fetchone()
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"El archivo no es una base de datos válida: {exc}") from exc

        pre_restore = self.backup_now("pre_restore")
        shutil.copy2(backup, self._db_path())
        return pre_restore
