"""Servicio del INVENTARIO: insumos, entradas/salidas y movimientos.

- Stock actual, mínimo y costo por insumo.
- Entradas y salidas manuales con historial completo de movimientos
  (cada movimiento guarda el stock resultante para auditoría).
- Alertas de stock bajo (la UI las muestra con colores e InfoBar).
"""
from __future__ import annotations

from typing import Optional

from app.core.database import Database
from app.core.services.validators import ValidationError
from app.signals import SignalBus

# Tipos de movimiento y su efecto sobre el stock
MOVEMENT_TYPES = {
    "entrada": "Entrada",
    "salida": "Salida",
    "venta": "Venta",        # generado automáticamente al cobrar
    "ajuste": "Ajuste",      # corrección manual del stock
}

UNITS = ["pza", "kg", "g", "L", "ml", "caja", "paquete", "litro", "bulto"]


class InventoryService:
    """CRUD de insumos + registro de movimientos."""

    def __init__(self, db: Database, bus: SignalBus):
        self.db = db
        self.bus = bus

    # ==================================================================
    # Insumos
    # ==================================================================

    def list_ingredients(self, search: str = "") -> list[dict]:
        sql = """
            SELECT *,
                   (stock <= min_stock AND min_stock > 0) AS is_low
              FROM ingredients
        """
        params: tuple = ()
        if search:
            sql += " WHERE name LIKE ?"
            params = (f"%{search}%",)
        sql += " ORDER BY name COLLATE NOCASE"
        return self.db.query(sql, params)

    def get_ingredient(self, ingredient_id: int) -> Optional[dict]:
        return self.db.one("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,))

    def add_ingredient(
        self,
        name: str,
        unit: str,
        stock: float = 0.0,
        min_stock: float = 0.0,
        cost: float = 0.0,
    ) -> int:
        name = self._clean_name(name)
        self._ensure_not_duplicated(name)
        row_id = self.db.execute(
            """
            INSERT INTO ingredients (name, unit, stock, min_stock, cost)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, unit or "pza", round(stock, 3), round(min_stock, 3), round(cost, 4)),
        )
        if stock > 0:
            # El stock inicial se registra como entrada para dejarlo en historial
            self.db.execute(
                """
                INSERT INTO movements (ingredient_id, type, quantity, stock_after, note)
                VALUES (?, 'entrada', ?, ?, 'Stock inicial')
                """,
                (row_id, round(stock, 3), round(stock, 3)),
            )
        self.bus.ingredientsChanged.emit()
        self.bus.movementsChanged.emit()
        return row_id

    def update_ingredient(
        self,
        ingredient_id: int,
        name: str,
        unit: str,
        min_stock: float,
        cost: float,
    ) -> None:
        """Edita datos del insumo. El stock se modifica SOLO con movimientos,
        para conservar la trazabilidad del inventario."""
        name = self._clean_name(name)
        dup = self.db.one(
            "SELECT id FROM ingredients WHERE name = ? COLLATE NOCASE AND id != ?",
            (name, ingredient_id),
        )
        if dup:
            raise ValidationError(f"Ya existe un insumo llamado «{name}».")
        self.db.execute(
            """
            UPDATE ingredients
               SET name = ?, unit = ?, min_stock = ?, cost = ?,
                   updated_at = datetime('now', 'localtime')
             WHERE id = ?
            """,
            (name, unit or "pza", round(min_stock, 3), round(cost, 4), ingredient_id),
        )
        self.bus.ingredientsChanged.emit()

    def delete_ingredient(self, ingredient_id: int) -> None:
        self.db.execute("DELETE FROM ingredients WHERE id = ?", (ingredient_id,))
        self.bus.ingredientsChanged.emit()
        self.bus.movementsChanged.emit()

    # ==================================================================
    # Movimientos (entradas / salidas manuales, ventas, ajustes)
    # ==================================================================

    def register_movement(
        self,
        ingredient_id: int,
        mtype: str,
        quantity: float,
        note: str = "",
        sale_id: Optional[int] = None,
        unit_cost: Optional[float] = None,
    ) -> dict:
        """Registra un movimiento y actualiza el stock.

        - entrada: +cantidad · salida: −cantidad · ajuste: deja el stock
          exactamente en `quantity` (delta = quantity − stock actual).
        - Las salidas no pueden dejar el stock en negativo.
        Devuelve el movimiento creado con su flag `is_low` para alertar.
        """
        if mtype not in MOVEMENT_TYPES:
            raise ValidationError(f"Tipo de movimiento inválido: {mtype}")

        ingredient = self.get_ingredient(ingredient_id)
        if ingredient is None:
            raise ValidationError("El insumo no existe.")

        quantity = float(quantity)
        if mtype in ("entrada", "salida") and quantity <= 0:
            raise ValidationError("La cantidad debe ser mayor a 0.")

        stock = float(ingredient["stock"])
        if mtype == "entrada":
            delta = quantity
        elif mtype == "salida":
            delta = -quantity
        elif mtype == "venta":
            delta = quantity  # ya viene con signo negativo desde la venta
        else:  # ajuste
            delta = quantity - stock

        new_stock = round(stock + delta, 3)
        if mtype == "salida" and new_stock < 0:
            raise ValidationError(
                f"Stock insuficiente: hay {stock:g} {ingredient['unit']} de "
                f"«{ingredient['name']}»."
            )

        with self.db.transaction():
            self.db.execute(
                "UPDATE ingredients SET stock = ?, updated_at = datetime('now','localtime')"
                " WHERE id = ?",
                (new_stock, ingredient_id),
            )
            movement_id = self.db.execute(
                """
                INSERT INTO movements
                    (ingredient_id, type, quantity, stock_after, unit_cost, note, sale_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ingredient_id,
                    mtype,
                    round(delta, 3),
                    new_stock,
                    unit_cost,
                    (note or "").strip() or None,
                    sale_id,
                ),
            )

        self.bus.ingredientsChanged.emit()
        self.bus.movementsChanged.emit()

        movement = self.db.one("SELECT * FROM movements WHERE id = ?", (movement_id,))
        movement["is_low"] = new_stock <= float(ingredient["min_stock"]) and float(
            ingredient["min_stock"]
        ) > 0
        movement["ingredient_name"] = ingredient["name"]
        return movement

    def list_movements(
        self,
        limit: int = 200,
        ingredient_id: Optional[int] = None,
        since: Optional[str] = None,
    ) -> list[dict]:
        """Historial de movimientos (más recientes primero)."""
        sql = """
            SELECT m.*, i.name AS ingredient_name, i.unit
              FROM movements m
              JOIN ingredients i ON i.id = m.ingredient_id
             WHERE 1 = 1
        """
        params: list = []
        if ingredient_id is not None:
            sql += " AND m.ingredient_id = ?"
            params.append(ingredient_id)
        if since:
            sql += " AND date(m.datetime) >= date(?)"
            params.append(since)
        sql += " ORDER BY m.datetime DESC, m.id DESC LIMIT ?"
        params.append(limit)
        return self.db.query(sql, tuple(params))

    def low_stock_ingredients(self) -> list[dict]:
        """Insumos en o por debajo de su stock mínimo."""
        return self.db.query(
            """
            SELECT * FROM ingredients
             WHERE min_stock > 0 AND stock <= min_stock
             ORDER BY (stock - min_stock)
            """
        )

    # ------------------------------------------------------------------
    # Validaciones
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_name(name: str) -> str:
        name = (name or "").strip()
        if not name:
            raise ValidationError("El nombre del insumo no puede estar vacío.")
        return name

    def _ensure_not_duplicated(self, name: str) -> None:
        dup = self.db.one(
            "SELECT id FROM ingredients WHERE name = ? COLLATE NOCASE", (name,)
        )
        if dup:
            raise ValidationError(f"Ya existe un insumo llamado «{name}».")
