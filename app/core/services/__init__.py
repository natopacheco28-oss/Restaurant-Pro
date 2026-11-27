"""Servicios de negocio de Restaurante Pro.

Capa intermedia entre la base de datos y la interfaz: validaciones,
transacciones atómicas y emisión de señales para actualizar la UI.
"""

from app.core.services.catalog_service import CatalogService, ValidationError
from app.core.services.inventory_service import InventoryService
from app.core.services.sales_service import (
    ORDER_TYPES,
    PAYMENT_METHODS,
    SalesService,
)
from app.core.services.stats_service import StatsService

__all__ = [
    "CatalogService",
    "InventoryService",
    "SalesService",
    "StatsService",
    "ValidationError",
    "ORDER_TYPES",
    "PAYMENT_METHODS",
]
