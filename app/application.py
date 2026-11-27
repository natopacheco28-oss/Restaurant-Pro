"""Ensamblado y arranque de Restaurante Pro.

Flujo de inicio:
1. Carpeta portable + comprobación de permisos de escritura.
2. Configuración (tema/acento) y logging rotativo en data/logs.
3. Inicialización de base de datos + migraciones versionadas.
4. Splash bootlogo con animación de aparición.
5. Si no hay clave maestra → asistente de bienvenida (primer arranque).
6. Ventana principal con navegación Fluent.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from qfluentwidgets import Theme, setTheme, setThemeColor

from app.core.backup import BackupManager
from app.core.database import Database
from app.core.migrations import run_migrations
from app.core.paths import (
    app_base_dir,
    config_file,
    database_path,
    ensure_directories,
    icon_asset_path,
    is_base_dir_writable,
    logs_dir,
    security_file,
)
from app.core.security import SecurityManager
from app.core.services.alerts_service import AlertsService
from app.core.services.catalog_service import CatalogService
from app.core.services.inventory_service import InventoryService
from app.core.services.sales_service import SalesService
from app.core.services.shopping_service import ShoppingService
from app.core.services.stats_service import StatsService
from app.core.settings import Settings
from app.context import init_context
from app.printing.printer import PrinterManager
from app.signals import SignalBus
from app.version import APP_NAME, APP_DESCRIPTION, APP_VERSION

log = logging.getLogger("restaurante")


def setup_logging() -> None:
    """Logging rotativo en data/logs/app.log + consola."""
    logs_dir().mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("restaurante")
    root.setLevel(logging.INFO)

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir() / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    root.addHandler(console)


def apply_theme(settings: Settings) -> None:
    """Aplica el tema (claro/oscuro/automático) y el color de acento."""
    theme_value = str(settings.get("ui.theme", "auto"))
    theme_map = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}
    try:
        setTheme(theme_map.get(theme_value, Theme.AUTO))
    except Exception:
        setTheme(Theme.LIGHT)
    accent = str(settings.get("ui.accent", "#ff7a1a"))
    try:
        setThemeColor(accent)
    except Exception:
        pass


def check_write_permissions() -> bool:
    """Verifica que la carpeta base sea escribible (programa portable)."""
    if is_base_dir_writable():
        return True
    message = (
        f"Restaurante Pro no puede escribir en su carpeta actual:\n"
        f"{app_base_dir()}\n\n"
        f"Los datos deben vivir junto al programa (carpetas «data» y «backups»).\n"
        f"Muévalo a una carpeta con permisos de escritura, por ejemplo:\n"
        f"C:\\RestaurantePro\n\n"
        f"La aplicación se cerrará."
    )
    QMessageBox.critical(None, "Permisos de escritura insuficientes", message)
    return False


def build_context() -> None:
    """Crea e inicializa todos los servicios de la aplicación."""
    settings = Settings(config_file())
    bus = SignalBus()
    db = Database(database_path()).connect()

    # Migraciones versionadas: actualizan el esquema sin perder datos
    run_migrations(db, log=lambda msg: log.info(msg))

    security = SecurityManager(security_file())
    backup = BackupManager(
        db_path=database_path,
        backup_dir=lambda: _backup_dir(settings),
        keep=10,
    )
    printer = PrinterManager(settings)

    # Almacén: inventario → listas de compras y alertas dependen de él
    inventory = InventoryService(db, bus, settings)
    shopping = ShoppingService(db, bus, inventory)
    alerts = AlertsService(db, inventory, settings)

    init_context(
        settings=settings,
        db=db,
        bus=bus,
        security=security,
        backup=backup,
        printer=printer,
        catalog=CatalogService(db, bus),
        inventory=inventory,
        shopping=shopping,
        alerts=alerts,
        sales=SalesService(db, bus, settings),
        stats=StatsService(db, settings),
    )


def _backup_dir(settings: Settings):
    """Carpeta de respaldos configurada (o la portable por defecto)."""
    from pathlib import Path

    configured = str(settings.get("paths.backup_dir", "") or "")
    if configured:
        return Path(configured)
    from app.core.paths import backups_default_dir

    return backups_default_dir()


def install_excepthook() -> None:
    """Convierte errores no capturados en registro + mensaje claro."""
    def hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.error("Error no capturado:\n%s", text)
        try:
            box = QMessageBox(QMessageBox.Icon.Critical, "Error inesperado",
                              "Ocurrió un error. El detalle quedó registrado en "
                              "data/logs/app.log\n\n"
                              f"{exc_type.__name__}: {exc_value}")
            box.exec()
        except Exception:
            pass

    sys.excepthook = hook


def run() -> int:
    """Punto de entrada de la aplicación."""
    # Política de escala en pantallas HiDPI (Windows)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(f"{APP_NAME} — {APP_DESCRIPTION}")
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(str(icon_asset_path())))

    ensure_directories()
    if not check_write_permissions():
        return 1

    setup_logging()
    log.info("Restaurante Pro %s — carpeta base: %s", APP_VERSION, app_base_dir())
    install_excepthook()

    # Base de datos y servicios (antes de la UI)
    try:
        build_context()
    except Exception as exc:
        log.exception("Fallo al inicializar la base de datos")
        QMessageBox.critical(None, "Error al iniciar",
                             f"No se pudo inicializar la base de datos:\n{exc}")
        return 1

    from app.context import ctx

    apply_theme(ctx.settings)

    # Splash bootlogo con animación
    from app.ui.splash import BootSplash

    splash = BootSplash(ctx.settings)
    splash.show_and_fade_in()
    app.processEvents()

    # Primer arranque: asistente de clave maestra
    if not ctx.security.is_configured():
        from app.ui.first_run import FirstRunWizard

        wizard = FirstRunWizard(ctx)
        if not wizard.exec():
            log.info("Asistente cancelado: la aplicación se cierra.")
            return 0

    # Ventana principal (el splash cede el paso con fundido)
    from app.ui.main_window import MainWindow

    window = MainWindow(ctx)
    splash.finish(window)

    return app.exec()
