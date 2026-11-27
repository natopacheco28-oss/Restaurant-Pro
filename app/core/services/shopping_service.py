"""Servicio de LISTAS DE COMPRAS SUGERIDAS del almacén.

- Genera automáticamente los renglones de insumos en stock bajo o agotados:
  cantidad sugerida = stock ideal − stock actual (o mínimo × 2 si no hay
  ideal), con proveedor y costo estimado.
- Las listas se guardan con estado (pendiente | comprada) y renglones
  editables (marcar, quitar, agregar, cambiar cantidad).
- «Registrar compra» convierte la lista en ENTRADAS de inventario con un
  clic (una transacción atómica) y marca la lista como comprada.
"""
from __future__ import annotations

from typing import Optional

from app.core.database import Database
from app.core.services.validators import ValidationError
from app.signals import SignalBus


class ShoppingService:
    """Generación, edición, persistencia y conversión de listas de compras."""

    STATUS_PENDING = "pendiente"
    STATUS_BOUGHT = "comprada"

    def __init__(self, db: Database, bus: SignalBus, inventory=None):
        self.db = db
        self.bus = bus
        self.inventory = inventory  # InventoryService (para la conversión)

    # ==================================================================
    # Sugerencia automática
    # ==================================================================

    def suggested_items(self) -> list[dict]:
        """Renglones sugeridos según stock bajo / agotado."""
        rows = self.db.query(
            """
            SELECT id, name, unit, stock, min_stock, ideal_stock, cost, supplier
              FROM ingredients
             WHERE stock <= 0 OR (min_stock > 0 AND stock <= min_stock)
             ORDER BY name COLLATE NOCASE
            """
        )
        items = []
        for row in rows:
            stock = float(row["stock"] or 0)
            ideal = float(row["ideal_stock"] or 0)
            minimum = float(row["min_stock"] or 0)
            if ideal > 0:
                target = ideal
            elif minimum > 0:
                target = minimum * 2
            else:
                target = 1.0  # agotado sin mínimos: sugerir 1 unidad
            quantity = round(max(target - stock, 0.0), 3)
            if quantity <= 0:
                quantity = 1.0
            cost = float(row["cost"] or 0)
            items.append({
                "ingredient_id": row["id"],
                "name": row["name"],
                "quantity": quantity,
                "unit": row["unit"],
                "estimated_cost": round(quantity * cost, 2),
                "supplier": row["supplier"] or "",
                "checked": 1,
            })
        return items

    @staticmethod
    def group_by_supplier(items: list[dict]) -> dict[str, list[dict]]:
        """Agrupa renglones por proveedor ('' → 'Sin proveedor')."""
        groups: dict[str, list[dict]] = {}
        for item in items:
            key = (item.get("supplier") or "").strip() or "Sin proveedor"
            groups.setdefault(key, []).append(item)
        return groups

    @staticmethod
    def total_cost(items: list[dict]) -> float:
        return round(sum(float(i.get("estimated_cost") or 0) for i in items), 2)

    # ==================================================================
    # Persistencia de listas
    # ==================================================================

    def create_list(self, items: list[dict], note: str = "") -> int:
        """Crea una lista nueva (estado pendiente) con los renglones dados."""
        list_id = self.db.execute(
            "INSERT INTO shopping_lists (note) VALUES (?)",
            ((note or "").strip() or None,),
        )
        for item in items:
            self.add_item(list_id, item)
        self.bus.shoppingListChanged.emit()
        return list_id

    def list_lists(self, limit: int = 50) -> list[dict]:
        return self.db.query(
            """
            SELECT l.*, (SELECT COUNT(*) FROM shopping_list_items li
                          WHERE li.list_id = l.id) AS item_count
              FROM shopping_lists l
             ORDER BY l.id DESC LIMIT ?
            """,
            (limit,),
        )

    def get_list(self, list_id: int) -> Optional[dict]:
        header = self.db.one(
            "SELECT * FROM shopping_lists WHERE id = ?", (list_id,)
        )
        if header is None:
            return None
        header["items"] = self.db.query(
            """
            SELECT * FROM shopping_list_items
             WHERE list_id = ?
             ORDER BY COALESCE(supplier, '') COLLATE NOCASE, name COLLATE NOCASE
            """,
            (list_id,),
        )
        return header

    def latest_list(self) -> Optional[dict]:
        row = self.db.one(
            "SELECT id FROM shopping_lists ORDER BY id DESC LIMIT 1"
        )
        return self.get_list(row["id"]) if row else None

    def set_status(self, list_id: int, status: str) -> None:
        if status not in (self.STATUS_PENDING, self.STATUS_BOUGHT):
            raise ValidationError(f"Estado inválido: {status}")
        self.db.execute(
            "UPDATE shopping_lists SET status = ? WHERE id = ?", (status, list_id)
        )
        self.bus.shoppingListChanged.emit()

    def delete_list(self, list_id: int) -> None:
        self.db.execute("DELETE FROM shopping_lists WHERE id = ?", (list_id,))
        self.bus.shoppingListChanged.emit()

    # ==================================================================
    # Renglones
    # ==================================================================

    def add_item(self, list_id: int, item: dict) -> int:
        name = (item.get("name") or "").strip()
        if not name:
            raise ValidationError("El renglón necesita un nombre.")
        quantity = float(item.get("quantity") or 0)
        if quantity <= 0:
            raise ValidationError("La cantidad debe ser mayor a 0.")
        return self.db.execute(
            """
            INSERT INTO shopping_list_items
                (list_id, ingredient_id, name, quantity, unit, estimated_cost,
                 supplier, checked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                list_id,
                item.get("ingredient_id"),
                name,
                round(quantity, 3),
                item.get("unit") or "pza",
                round(float(item.get("estimated_cost") or 0), 2),
                (item.get("supplier") or "").strip() or None,
                1 if item.get("checked", 1) else 0,
            ),
        )

    def update_item(self, item_id: int, quantity: Optional[float] = None,
                    estimated_cost: Optional[float] = None,
                    supplier: Optional[str] = None,
                    checked: Optional[bool] = None) -> None:
        """Actualiza campos de un renglón (cantidad editable desde la tabla)."""
        row = self.db.one(
            "SELECT * FROM shopping_list_items WHERE id = ?", (item_id,)
        )
        if row is None:
            raise ValidationError("El renglón no existe.")
        self.db.execute(
            """
            UPDATE shopping_list_items
               SET quantity = ?, estimated_cost = ?, supplier = ?, checked = ?
             WHERE id = ?
            """,
            (
                round(float(row["quantity"] if quantity is None else quantity), 3),
                round(float(row["estimated_cost"] if estimated_cost is None
                            else estimated_cost), 2),
                (row["supplier"] if supplier is None else supplier) or None,
                int(row["checked"] if checked is None else (1 if checked else 0)),
                item_id,
            ),
        )
        self.bus.shoppingListChanged.emit()

    def remove_item(self, item_id: int) -> None:
        self.db.execute("DELETE FROM shopping_list_items WHERE id = ?", (item_id,))
        self.bus.shoppingListChanged.emit()

    def toggle_checked(self, item_id: int) -> None:
        self.db.execute(
            "UPDATE shopping_list_items SET checked = 1 - checked WHERE id = ?",
            (item_id,),
        )
        self.bus.shoppingListChanged.emit()

    # ==================================================================
    # Conversión de la lista en ENTRADAS de inventario
    # ==================================================================

    def convert_to_entries(self, list_id: int, user: str = "") -> dict:
        """Convierte los renglones (con insumo ligado y cantidad > 0) en
        entradas de kardex con lote nuevo, y marca la lista como comprada.

        Los renglones manuales sin insumo ligado se omiten (se reportan).
        """
        if self.inventory is None:
            raise ValidationError("El servicio de inventario no está disponible.")

        header = self.get_list(list_id)
        if header is None:
            raise ValidationError("La lista no existe.")
        if header["status"] == self.STATUS_BOUGHT:
            raise ValidationError("La lista ya fue marcada como comprada.")

        rows = [it for it in header["items"]
                if it["ingredient_id"] and float(it["quantity"]) > 0]
        skipped = len(header["items"]) - len(rows)

        created = 0
        with self.db.transaction():
            for item in rows:
                quantity = float(item["quantity"])
                unit_cost = None
                if float(item["estimated_cost"] or 0) > 0:
                    unit_cost = round(float(item["estimated_cost"]) / quantity, 4)
                self.inventory.register_movement(
                    int(item["ingredient_id"]),
                    "entrada",
                    quantity,
                    note=f"Compra — lista #{list_id}",
                    unit_cost=unit_cost,
                    supplier=item["supplier"] or "",
                    user=user,
                    manage_transaction=False,  # ya hay transacción abierta
                )
                created += 1
            self.set_status(list_id, self.STATUS_BOUGHT)

        self.bus.ingredientsChanged.emit()
        self.bus.movementsChanged.emit()
        return {"created": created, "skipped": skipped, "list_id": list_id}
