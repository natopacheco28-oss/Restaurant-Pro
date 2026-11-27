"""Bus de señales global de Restaurante Pro.

Los servicios emiten señales cuando cambian los datos y las interfaces se
suscriben para refrescar sus tablas/listas al instante, SIN reiniciar el
programa (requisito del catálogo y del inventario).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class SignalBus(QObject):
    """Concentrador de notificaciones de cambio de datos."""

    categoriesChanged = Signal()      # catálogo: categorías
    productsChanged = Signal()        # catálogo: productos / recetas
    ingredientsChanged = Signal()     # inventario: insumos
    movementsChanged = Signal()       # inventario: movimientos
    salesChanged = Signal()           # caja: ventas (incluye nueva venta)
    cashSessionChanged = Signal()     # caja: apertura / cierre de caja
    settingsChanged = Signal()        # ajustes: configuración modificada
    editModeChanged = Signal(bool)    # seguridad: modo edición on/off
