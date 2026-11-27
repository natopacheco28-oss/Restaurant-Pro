"""Contexto de ejecución de Restaurante Pro.

Contenedor de los servicios activos de la aplicación (configuración, base de
datos, seguridad, respaldos, servicios y bus de señales). Se inicializa una
sola vez en `app.application.run()` y la interfaz accede por `ctx`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AppContext:
    """Servicios vivos de la aplicación."""

    settings: Optional[object] = None
    db: Optional[object] = None
    bus: Optional[object] = None
    security: Optional[object] = None
    backup: Optional[object] = None
    printer: Optional[object] = None
    catalog: Optional[object] = None
    inventory: Optional[object] = None
    shopping: Optional[object] = None
    alerts: Optional[object] = None
    sales: Optional[object] = None
    stats: Optional[object] = None


# Instancia global (rellenada por app.application.init_context)
ctx = AppContext()


def init_context(settings, db, bus, security, backup, printer,
                 catalog, inventory, shopping, alerts,
                 sales, stats) -> AppContext:
    """Registra los servicios en el contexto global."""
    ctx.settings = settings
    ctx.db = db
    ctx.bus = bus
    ctx.security = security
    ctx.backup = backup
    ctx.printer = printer
    ctx.catalog = catalog
    ctx.inventory = inventory
    ctx.shopping = shopping
    ctx.alerts = alerts
    ctx.sales = sales
    ctx.stats = stats
    return ctx
