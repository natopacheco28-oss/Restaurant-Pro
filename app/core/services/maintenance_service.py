"""Mantenimiento de datos: borrado operativo con integridad garantizada.

`reset_operational_data` elimina TODA la información operativa en un orden
seguro de claves foráneas (hijos antes que padres) y reinicia el stock de
los insumos a 0 — el kardex es la fuente de la verdad del stock y, al
borrarse, no queda registro que lo respalde.

Se conserva: catálogo (categorías, productos, recetas), la definición de
los insumos, los ajustes (JSON) y la clave maestra.
"""
from __future__ import annotations

# Orden de borrado seguro (referencias FK: hijos antes que padres):
#   movements referencia a sales (sale_id) y lots (lot_id)
#   sale_items referencia a sales · sales referencia a cash_sessions
WIPE_ORDER = (
    "alert_dismissals",
    "shopping_list_items",
    "shopping_lists",
    "movements",
    "lots",
    "sale_items",
    "sales",
    "cash_sessions",
)


def reset_operational_data(db) -> dict[str, int]:
    """Borra ventas, órdenes, caja, kardex, lotes y listas; stock → 0.

    Todo dentro de una transacción (o no se borra nada). Devuelve un
    diccionario con la cantidad de filas eliminadas por tabla.
    """
    counts: dict[str, int] = {}
    with db.transaction() as conn:
        for table in WIPE_ORDER:
            cursor = conn.execute(f"DELETE FROM {table}")
            counts[table] = cursor.rowcount if cursor.rowcount >= 0 else 0
        # Sin kardex no hay base para el stock: reiniciar a cero
        conn.execute("UPDATE ingredients SET stock = 0")
    return counts
