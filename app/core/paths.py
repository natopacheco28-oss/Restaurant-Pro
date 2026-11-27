"""Rutas portables de Restaurante Pro.

Toda la información (base de datos, configuración, imágenes, respaldos y
registros) vive en carpetas junto al ejecutable, nunca en el perfil del
usuario. Esto mantiene la filosofía portable de ABCell Pro:

    RestaurantePro/
    ├── RestaurantePro.exe   (o main.py en modo desarrollo)
    ├── assets/              (recursos empaquetados: logo, icono)
    ├── data/                (base de datos, config, imágenes, logs)
    └── backups/             (respaldos automáticos y manuales)

La carpeta base se detecta a partir de `sys.executable` cuando el programa
está empaquetado con PyInstaller, y a partir del código fuente en desarrollo.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


def app_base_dir() -> Path:
    """Carpeta base del programa.

    - Empaquetado (PyInstaller): carpeta que contiene el .exe.
    - Desde el código fuente: raíz del repositorio (carpeta padre de `app/`).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # paths.py está en <raíz>/app/core/paths.py → parents[2] es la raíz
    return Path(__file__).resolve().parents[2]


def resources_dir() -> Path:
    """Carpeta de recursos empaquetados (assets/ logo e icono).

    Con PyInstaller los datos van a `_internal/` (onedir) y `sys._MEIPASS`
    apunta a esa carpeta; en desarrollo es `<raíz>/assets`.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "assets"
        return app_base_dir() / "_internal" / "assets"
    return app_base_dir() / "assets"


def logo_asset_path() -> Path:
    """Logo oficial del proyecto (assets/logo.png)."""
    return resources_dir() / "logo.png"


def icon_asset_path() -> Path:
    """Icono oficial del proyecto (assets/icon.ico)."""
    return resources_dir() / "icon.ico"


# ------------------------------------------------------------------
# Carpetas de datos portables
# ------------------------------------------------------------------

def data_dir() -> Path:
    return app_base_dir() / "data"


def images_dir() -> Path:
    """Imágenes del usuario (logo personalizado, fotos de productos)."""
    return data_dir() / "imgs"


def logs_dir() -> Path:
    return data_dir() / "logs"


def backups_default_dir() -> Path:
    """Carpeta de respaldos por defecto (configurable en Ajustes)."""
    return app_base_dir() / "backups"


def database_path() -> Path:
    return data_dir() / "restaurante.db"


def config_file() -> Path:
    """Archivo de configuración JSON (Ajustes del programa)."""
    return data_dir() / "config.json"


def security_file() -> Path:
    """Archivo con el hash (con sal) de la clave maestra."""
    return data_dir() / "security.json"


def ensure_directories() -> None:
    """Crea las carpetas portables si no existen."""
    for d in (data_dir(), images_dir(), logs_dir(), backups_default_dir()):
        d.mkdir(parents=True, exist_ok=True)


def is_base_dir_writable() -> bool:
    """Comprueba que se pueda escribir en la carpeta base.

    Si falla (Program Files, carpeta de sistema, disco protegido, etc.) la
    aplicación muestra un mensaje sugiriendo moverla a C:\\RestaurantePro.
    """
    probe = app_base_dir() / ".write_test"
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        # Último recurso: comprobar con un archivo temporal del sistema
        try:
            with tempfile.NamedTemporaryFile(
                dir=str(app_base_dir()), prefix=".write_test_"
            ) as fh:
                fh.write(b"ok")
            return True
        except OSError:
            return False


def resolve_portable(stored: str | None) -> Path:
    """Resuelve una ruta guardada en configuración/base de datos.

    Las rutas relativas (ej. `data/imgs/x.png`) se interpretan respecto a la
    carpeta base para que el programa siga siendo portable al moverlo.
    """
    if not stored:
        return Path()
    p = Path(stored)
    if p.is_absolute():
        return p
    return app_base_dir() / p


def portable_path(path: Path) -> str:
    """Convierte una ruta absoluta a relativa a la base si es posible."""
    try:
        return str(Path(path).resolve().relative_to(app_base_dir()))
    except ValueError:
        return str(path)
