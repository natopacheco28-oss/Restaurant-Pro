"""Servicio del INVENTARIO (almacén): insumos, lotes, kardex y estancados.

- Insumos con unidad, stock actual, mínimo, IDEAL de reposición, costo,
  proveedor habitual y días de aviso de caducidad propios.
- Kardex inmutable: cada movimiento (entrada, salida, merma/desperdicio,
  ajuste o consumo por venta) registra fecha/hora, insumo, tipo, cantidad,
  costo unitario, lote, proveedor, motivo y usuario. Los movimientos NO se
  editan ni se borran: solo se corrigen con un ajuste.
- Lotes con caducidad: cada entrada crea un lote y TODAS las salidas
  descuentan primero el lote que caduca antes (PEPS/FEFO).
- Detección de insumos sin movimiento (stock estancado).
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime
from typing import Optional

from app.core.database import Database
from app.core.services.validators import ValidationError
from app.signals import SignalBus

# Tipos de movimiento y su etiqueta visible
MOVEMENT_TYPES = {
    "entrada": "Entrada",
    "salida": "Salida",
    "merma": "Merma / desperdicio",
    "venta": "Consumo por venta",
    "ajuste": "Ajuste",
}

# Tipos que descuentan stock (salidas reales)
OUT_TYPES = ("salida", "merma", "venta")

UNITS = ["pza", "kg", "g", "L", "ml", "caja", "paquete", "litro", "bulto"]

# Motivos sugeridos para merma/desperdicio
MERMA_REASONS = [
    "Caducado", "Dañado o derrame", "Error de preparación",
    "Error de pedido", "Degustación", "Otro",
]


# ======================================================================
# Helpers de nivel de módulo (reutilizables sin instancia del servicio;
# NO abren transacciones: el llamador controla la atomicidad)
# ======================================================================

def allocate_fefo(db: Database, ingredient_id: int, quantity: float,
                  force_lot_id: Optional[int] = None) -> list[tuple]:
    """Distribuye `quantity` entre los lotes por PEPS/FEFO.

    Orden: primero los lotes CON caducidad (el que caduca antes primero),
    luego los sin caducidad por antigüedad. Actualiza `lots.quantity` y
    devuelve [(lot_id, cantidad_consumida)]; un sobrante sin lote se
    devuelve como (None, cantidad). Con `force_lot_id` solo descuenta de
    ese lote (para mermas de un lote concreto).
    """
    if force_lot_id is not None:
        lots = db.query(
            "SELECT id, quantity FROM lots WHERE id = ? AND ingredient_id = ?"
            " AND quantity > 0",
            (force_lot_id, ingredient_id),
        )
    else:
        lots = db.query(
            """
            SELECT id, quantity FROM lots
             WHERE ingredient_id = ? AND quantity > 0
             ORDER BY (expiration_date IS NULL) ASC, expiration_date ASC, id ASC
            """,
            (ingredient_id,),
        )

    remaining = float(quantity)
    allocations: list[tuple] = []
    for lot in lots:
        if remaining <= 1e-9:
            break
        take = min(float(lot["quantity"]), remaining)
        db.execute(
            "UPDATE lots SET quantity = quantity - ? WHERE id = ?",
            (round(take, 3), lot["id"]),
        )
        allocations.append((lot["id"], round(take, 3)))
        remaining -= take
    if remaining > 1e-9:
        allocations.append((None, round(remaining, 3)))
    return allocations


def consume_for_sale(db: Database, ingredient_id: int, quantity: float,
                     sale_id: int, folio: int = 0, user: str = "") -> dict:
    """Descuenta inventario por una venta (un insumo de la receta).

    Sigue PEPS/FEFO, actualiza el stock y deja las filas de kardex
    (una por lote consumido). Si no se pasa `folio`, se consulta de la venta.
    Devuelve {"stock_after", "is_low", "ingredient_name"} para las alertas.
    """
    ingredient = db.one("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,))
    if ingredient is None:
        raise ValidationError("El insumo de la receta no existe.")

    if folio <= 0 and sale_id:
        sale = db.one("SELECT folio FROM sales WHERE id = ?", (sale_id,))
        folio = int(sale["folio"]) if sale else 0

    quantity = float(quantity)
    new_stock = round(float(ingredient["stock"]) - quantity, 3)
    db.execute(
        "UPDATE ingredients SET stock = ?, updated_at = datetime('now','localtime')"
        " WHERE id = ?",
        (new_stock, ingredient_id),
    )

    note = f"Venta folio #{folio:06d}"
    allocations = allocate_fefo(db, ingredient_id, quantity)
    if not allocations:  # sin lotes registrados (dato antiguo): fila simple
        allocations = [(None, round(quantity, 3))]

    for lot_id, consumed in allocations:
        db.execute(
            """
            INSERT INTO movements
                (ingredient_id, type, quantity, stock_after, lot_id, note,
                 user, sale_id)
            VALUES (?, 'venta', ?, ?, ?, ?, ?, ?)
            """,
            (ingredient_id, -round(consumed, 3), new_stock, lot_id, note,
             user or None, sale_id if sale_id and sale_id > 0 else None),
        )

    min_stock = float(ingredient["min_stock"] or 0)
    return {
        "stock_after": new_stock,
        "is_low": min_stock > 0 and new_stock <= min_stock,
        "ingredient_name": ingredient["name"],
    }


# ======================================================================
# Servicio
# ======================================================================

class InventoryService:
    """CRUD de insumos + kardex completo + lotes + estancados."""

    def __init__(self, db: Database, bus: SignalBus, settings=None):
        self.db = db
        self.bus = bus
        self.settings = settings

    # ------------------------------------------------------------------
    # Configuración global de caducidad
    # ------------------------------------------------------------------

    def default_warning_days(self) -> int:
        try:
            return int(self.settings.get("inventory.expiry_warning_days", 7) or 7)
        except (AttributeError, TypeError, ValueError):
            return 7

    def warning_days_for(self, ingredient: dict) -> int:
        """Días de aviso del insumo o el global si no tiene (0 = global)."""
        own = int(ingredient.get("warning_days") or 0)
        return own if own > 0 else self.default_warning_days()

    # ==================================================================
    # Insumos
    # ==================================================================

    def list_ingredients(self, search: str = "") -> list[dict]:
        """Insumos con `is_low` (stock bajo) y `estado` (normal/bajo/agotado)."""
        sql = """
            SELECT *,
                   (stock <= min_stock AND min_stock > 0) AS is_low,
                   CASE
                       WHEN stock <= 0 THEN 'agotado'
                       WHEN min_stock > 0 AND stock <= min_stock THEN 'bajo'
                       ELSE 'normal'
                   END AS estado
              FROM ingredients
        """
        params: tuple = ()
        if search:
            sql += " WHERE name LIKE ? OR supplier LIKE ?"
            params = (f"%{search}%", f"%{search}%")
        sql += " ORDER BY name COLLATE NOCASE"
        return self.db.query(sql, params)

    def get_ingredient(self, ingredient_id: int) -> Optional[dict]:
        """Fila del insumo con `estado` e `is_low` calculados (como la lista)."""
        ingredient = self.db.one(
            "SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)
        )
        if ingredient is None:
            return None
        stock = float(ingredient["stock"] or 0)
        min_stock = float(ingredient["min_stock"] or 0)
        ingredient["is_low"] = stock <= min_stock and min_stock > 0
        ingredient["estado"] = ("agotado" if stock <= 0
                                else "bajo" if ingredient["is_low"] else "normal")
        return ingredient

    def add_ingredient(
        self,
        name: str,
        unit: str,
        stock: float = 0.0,
        min_stock: float = 0.0,
        cost: float = 0.0,
        ideal_stock: float = 0.0,
        warning_days: int = 0,
        supplier: str = "",
    ) -> int:
        name = self._clean_name(name)
        self._ensure_not_duplicated(name)
        # El stock se inserta en 0 y luego se registra como ENTRADA para que
        # quede en el kardex con su lote (sin duplicar la cantidad).
        row_id = self.db.execute(
            """
            INSERT INTO ingredients
                (name, unit, stock, min_stock, cost, ideal_stock, warning_days,
                 supplier)
            VALUES (?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (name, unit or "pza", round(min_stock, 3),
             round(cost, 4), round(ideal_stock, 3), int(warning_days or 0),
             (supplier or "").strip()),
        )
        if stock > 0:
            # El stock inicial se registra como entrada (con lote) para
            # dejarlo en el kardex y en el sistema de lotes
            self.register_movement(
                row_id, "entrada", stock, note="Stock inicial",
                unit_cost=cost, supplier=supplier,
            )
        else:
            self.bus.ingredientsChanged.emit()
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
        ideal_stock: Optional[float] = None,
        warning_days: Optional[int] = None,
        supplier: Optional[str] = None,
    ) -> None:
        """Edita datos del insumo. El stock se modifica SOLO con movimientos."""
        name = self._clean_name(name)
        dup = self.db.one(
            "SELECT id FROM ingredients WHERE name = ? COLLATE NOCASE AND id != ?",
            (name, ingredient_id),
        )
        if dup:
            raise ValidationError(f"Ya existe un insumo llamado «{name}».")

        current = self.get_ingredient(ingredient_id)
        if current is None:
            raise ValidationError("El insumo no existe.")
        if ideal_stock is None:
            ideal_stock = float(current["ideal_stock"] or 0)
        if warning_days is None:
            warning_days = int(current["warning_days"] or 0)
        if supplier is None:
            supplier = current["supplier"] or ""

        self.db.execute(
            """
            UPDATE ingredients
               SET name = ?, unit = ?, min_stock = ?, cost = ?, ideal_stock = ?,
                   warning_days = ?, supplier = ?,
                   updated_at = datetime('now', 'localtime')
             WHERE id = ?
            """,
            (name, unit or "pza", round(min_stock, 3), round(cost, 4),
             round(float(ideal_stock), 3), int(warning_days or 0),
             (supplier or "").strip(), ingredient_id),
        )
        self.bus.ingredientsChanged.emit()

    def delete_ingredient(self, ingredient_id: int) -> None:
        self.db.execute("DELETE FROM ingredients WHERE id = ?", (ingredient_id,))
        self.bus.ingredientsChanged.emit()
        self.bus.movementsChanged.emit()

    # ==================================================================
    # Kardex: registro de movimientos (INMUTABLE)
    # ==================================================================

    def register_movement(
        self,
        ingredient_id: int,
        mtype: str,
        quantity: float,
        note: str = "",
        sale_id: Optional[int] = None,
        unit_cost: Optional[float] = None,
        supplier: str = "",
        user: str = "",
        reason: str = "",
        expiration: Optional[str] = None,
        lot_number: str = "",
        force_lot_id: Optional[int] = None,
        manage_transaction: bool = True,
    ) -> dict:
        """Registra un movimiento de kardex y actualiza stock y lotes.

        - entrada: crea un lote (número auto si no se da) con caducidad
          opcional; valida que la caducidad no sea anterior a hoy.
        - salida / merma: descuenta por PEPS/FEFO (o del lote indicado con
          `force_lot_id`); una fila de kardex por lote consumido.
        - ajuste: deja el stock exactamente en `quantity` (delta por FEFO
          si baja, lote nuevo si sube).
        - venta: delega en `consume_for_sale` (usado por la Caja).
        - `manage_transaction=False` cuando el llamador ya abrió una
          transacción (ej. conversión de lista de compras).

        Devuelve {"rows", "is_low", "ingredient_name", "stock_after"}.
        Los movimientos no se editan ni se borran (kardex confiable).
        """
        if mtype not in MOVEMENT_TYPES:
            raise ValidationError(f"Tipo de movimiento inválido: {mtype}")

        ingredient = self.get_ingredient(ingredient_id)
        if ingredient is None:
            raise ValidationError("El insumo no existe.")

        quantity = float(quantity)
        stock = float(ingredient["stock"])
        tx = self.db.transaction() if manage_transaction else nullcontext()

        with tx:
            if mtype == "venta":
                result = consume_for_sale(
                    self.db, ingredient_id, quantity, sale_id or 0, user=user
                )
                self._emit()
                result["rows"] = []
                return result

            if mtype == "entrada":
                if quantity <= 0:
                    raise ValidationError("La cantidad debe ser mayor a 0.")
                self._validate_expiration(expiration)
                new_stock = round(stock + quantity, 3)
                self._set_stock(ingredient_id, new_stock)
                lot_id = self._create_lot(
                    ingredient_id, quantity,
                    unit_cost if unit_cost is not None else float(ingredient["cost"] or 0),
                    supplier or ingredient.get("supplier") or "",
                    lot_number, expiration,
                )
                rows = [self._insert_movement(
                    ingredient_id, mtype, round(quantity, 3), new_stock,
                    lot_id=lot_id,
                    unit_cost=unit_cost if unit_cost is not None else float(ingredient["cost"] or 0),
                    supplier=supplier, user=user, reason=reason, note=note,
                )]

            elif mtype in ("salida", "merma"):
                if quantity <= 0:
                    raise ValidationError("La cantidad debe ser mayor a 0.")
                new_stock = round(stock - quantity, 3)
                if new_stock < 0:
                    raise ValidationError(
                        f"Stock insuficiente: hay {stock:g} {ingredient['unit']} de "
                        f"«{ingredient['name']}»."
                    )
                self._set_stock(ingredient_id, new_stock)
                allocations = allocate_fefo(
                    self.db, ingredient_id, quantity, force_lot_id=force_lot_id
                )
                rows = []
                for lot_id, consumed in allocations:
                    lot_cost = self._lot_cost(lot_id)
                    rows.append(self._insert_movement(
                        ingredient_id, mtype, -round(consumed, 3), new_stock,
                        lot_id=lot_id,
                        unit_cost=unit_cost if unit_cost is not None else lot_cost,
                        supplier=supplier, user=user, reason=reason, note=note,
                    ))

            else:  # ajuste
                target = quantity
                if target < 0:
                    raise ValidationError("El stock objetivo no puede ser negativo.")
                delta = round(target - stock, 3)
                new_stock = round(target, 3)
                self._set_stock(ingredient_id, new_stock)
                if delta < 0:
                    allocate_fefo(self.db, ingredient_id, -delta)
                elif delta > 0:
                    self._create_lot(
                        ingredient_id, delta,
                        unit_cost if unit_cost is not None else float(ingredient["cost"] or 0),
                        supplier or ingredient.get("supplier") or "",
                        lot_number or "", None,
                    )
                rows = [self._insert_movement(
                    ingredient_id, mtype, delta, new_stock,
                    lot_id=None, unit_cost=unit_cost, supplier=supplier,
                    user=user, reason=reason, note=note or "Ajuste de inventario",
                )]

        self._emit()
        min_stock = float(ingredient["min_stock"] or 0)
        return {
            "rows": rows,
            "is_low": min_stock > 0 and new_stock <= min_stock,
            "ingredient_name": ingredient["name"],
            "stock_after": new_stock,
        }

    def _emit(self) -> None:
        self.bus.ingredientsChanged.emit()
        self.bus.movementsChanged.emit()
        self.bus.lotsChanged.emit()

    @staticmethod
    def _folio_of(sale_id: int) -> int:
        """Folio de una venta (para la nota del kardex)."""
        return 0  # se resuelve en consume_for_sale vía la nota de la venta

    # ------------------------------------------------------------------
    # Lotes y caducidades
    # ------------------------------------------------------------------

    def list_lots(self, ingredient_id: Optional[int] = None,
                  only_active: bool = True) -> list[dict]:
        """Lotes con días restantes y estado del semáforo (por urgencia)."""
        sql = """
            SELECT l.*, i.name AS ingredient_name, i.unit, i.min_stock,
                   i.warning_days,
                   CAST(julianday(l.expiration_date) - julianday('now') AS INTEGER)
                       AS days_left
              FROM lots l
              JOIN ingredients i ON i.id = l.ingredient_id
             WHERE 1 = 1
        """
        params: list = []
        if ingredient_id is not None:
            sql += " AND l.ingredient_id = ?"
            params.append(ingredient_id)
        if only_active:
            sql += " AND l.quantity > 0"
        sql += " ORDER BY (l.expiration_date IS NULL) ASC, l.expiration_date ASC, l.id ASC"
        lots = self.db.query(sql, tuple(params))

        result = []
        for lot in lots:
            expiration = lot.get("expiration_date")
            if expiration:
                days = int(lot["days_left"])
                warn = self.warning_days_for(lot)
                estado = "vencido" if days < 0 else (
                    "por_caducar" if days <= warn else "vigente")
            else:
                days = None
                estado = "sin_caducidad"
            lot["days_left"] = days
            lot["warn_days"] = self.warning_days_for(lot)
            lot["estado"] = estado
            lot["value"] = round(float(lot["quantity"]) * float(lot["unit_cost"] or 0), 2)
            result.append(lot)
        # Vencidos primero, luego por caducar, luego vigentes/sin caducidad
        order = {"vencido": 0, "por_caducar": 1, "vigente": 2, "sin_caducidad": 3}
        result.sort(key=lambda l: (order[l["estado"]],
                                   l["expiration_date"] or "9999-12-31"))
        return result

    def expiring_lots(self, only_warned: bool = True) -> list[dict]:
        """Lotes vencidos o próximos a vencer, ordenados por urgencia."""
        lots = self.list_lots(only_active=True)
        if only_warned:
            return [l for l in lots if l["estado"] in ("vencido", "por_caducar")]
        return [l for l in lots if l["estado"] != "sin_caducidad"]

    def _create_lot(self, ingredient_id: int, quantity: float, unit_cost: float,
                    supplier: str, lot_number: str,
                    expiration: Optional[str]) -> int:
        if not lot_number:
            lot_number = datetime.now().strftime("L%Y%m%d-%H%M%S")
        return self.db.execute(
            """
            INSERT INTO lots (ingredient_id, lot_number, expiration_date,
                              quantity, unit_cost, supplier)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ingredient_id, lot_number, expiration, round(quantity, 3),
             round(unit_cost, 4), (supplier or "").strip() or None),
        )

    def _lot_cost(self, lot_id: Optional[int]) -> float:
        if lot_id is None:
            return 0.0
        row = self.db.one("SELECT unit_cost FROM lots WHERE id = ?", (lot_id,))
        return float(row["unit_cost"]) if row else 0.0

    @staticmethod
    def _validate_expiration(expiration: Optional[str]) -> None:
        if not expiration:
            return
        try:
            exp = date.fromisoformat(str(expiration)[:10])
        except ValueError as exc:
            raise ValidationError("La fecha de caducidad no es válida.") from exc
        if exp < date.today():
            raise ValidationError(
                "La caducidad no puede ser anterior a la fecha de entrada.")

    def _set_stock(self, ingredient_id: int, stock: float) -> None:
        self.db.execute(
            "UPDATE ingredients SET stock = ?, updated_at = datetime('now','localtime')"
            " WHERE id = ?",
            (stock, ingredient_id),
        )

    def _insert_movement(self, ingredient_id: int, mtype: str, quantity: float,
                         stock_after: float, lot_id: Optional[int],
                         unit_cost: Optional[float], supplier: str, user: str,
                         reason: str, note: str) -> int:
        return self.db.execute(
            """
            INSERT INTO movements
                (ingredient_id, type, quantity, stock_after, unit_cost, note,
                 lot_id, supplier, user, reason, sale_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (ingredient_id, mtype, quantity, stock_after, unit_cost,
             (note or "").strip() or None, lot_id,
             (supplier or "").strip() or None, (user or "").strip() or None,
             (reason or "").strip() or None),
        )

    # ==================================================================
    # Consultas del kardex
    # ==================================================================

    def list_movements(
        self,
        limit: int = 200,
        ingredient_id: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        mtype: Optional[str] = None,
        reason_search: str = "",
    ) -> list[dict]:
        """Kardex filtrable por insumo, tipo, rango de fechas y motivo."""
        sql = """
            SELECT m.*, i.name AS ingredient_name, i.unit, l.lot_number
              FROM movements m
              JOIN ingredients i ON i.id = m.ingredient_id
              LEFT JOIN lots l ON l.id = m.lot_id
             WHERE 1 = 1
        """
        params: list = []
        if ingredient_id is not None:
            sql += " AND m.ingredient_id = ?"
            params.append(ingredient_id)
        if since:
            sql += " AND date(m.datetime) >= date(?)"
            params.append(since)
        if until:
            sql += " AND date(m.datetime) <= date(?)"
            params.append(until)
        if mtype:
            sql += " AND m.type = ?"
            params.append(mtype)
        if reason_search:
            sql += " AND (COALESCE(m.reason, '') LIKE ? OR COALESCE(m.note, '') LIKE ?)"
            like = f"%{reason_search}%"
            params.extend([like, like])
        sql += " ORDER BY m.datetime DESC, m.id DESC LIMIT ?"
        params.append(limit)
        return self.db.query(sql, tuple(params))

    def kardex_rows(self, **filters) -> list[dict]:
        """Filas completas del kardex para exportar (sin límite práctico)."""
        return self.list_movements(limit=10000, **filters)

    # ==================================================================
    # Stock bajo / estancados / valor
    # ==================================================================

    def low_stock_ingredients(self) -> list[dict]:
        """Insumos en o por debajo de su stock mínimo (incluye agotados)."""
        return self.db.query(
            """
            SELECT * FROM ingredients
             WHERE stock <= 0 OR (min_stock > 0 AND stock <= min_stock)
             ORDER BY (stock - min_stock)
            """
        )

    def stale_ingredients(self, days: Optional[int] = None) -> list[dict]:
        """Insumos con existencia SIN salidas (salida/merma/venta) en X días.

        `days` por defecto sale de Ajustes (inventory.stale_days, 30).
        Devuelve días estancados, valor inmovilizado y última salida.
        El "ancla" para insumos que nunca tuvieron salidas es la fecha de su
        primer movimiento (entrada) o la más antigua registrada.
        """
        if days is None:
            days = self._stale_days()
        # Semántica: si YA HUBO salidas, es estancado cuando la última fue
        # hace más de X días; si nunca tuvo salidas, cuando exista hace más
        # de X días (anclada a su primer movimiento).
        sql = f"""
            SELECT * FROM (
                SELECT i.*,
                       (SELECT MAX(date(m.datetime)) FROM movements m
                         WHERE m.ingredient_id = i.id
                           AND m.type IN ('salida', 'merma', 'venta')) AS last_out,
                       CAST(julianday('now') - julianday(COALESCE(
                            (SELECT MAX(date(m.datetime)) FROM movements m
                              WHERE m.ingredient_id = i.id
                                AND m.type IN ('salida', 'merma', 'venta')),
                            (SELECT MIN(date(m.datetime)) FROM movements m
                              WHERE m.ingredient_id = i.id))) AS INTEGER)
                           AS days_stale
                  FROM ingredients i
            )
             WHERE stock > 0
               AND (
                    (last_out IS NOT NULL
                        AND last_out < date('now', '-{int(days)} days'))
                    OR
                    (last_out IS NULL AND days_stale >= {int(days)})
               )
             ORDER BY days_stale DESC
        """
        # `days` ya está incrustado como entero validado en la consulta
        rows = self.db.query(sql)
        for row in rows:
            row["value"] = round(float(row["stock"]) * float(row["cost"] or 0), 2)
        return rows

    def _stale_days(self) -> int:
        try:
            return int(self.settings.get("inventory.stale_days", 30) or 30)
        except (AttributeError, TypeError, ValueError):
            return 30

    def inventory_value(self) -> float:
        row = self.db.one(
            "SELECT COALESCE(SUM(stock * cost), 0) AS v FROM ingredients"
        )
        return round(float(row["v"] or 0), 2)

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
