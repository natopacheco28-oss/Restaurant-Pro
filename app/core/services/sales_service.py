"""Servicio de la CAJA: sesiones de caja, cobro de ventas y folios.

- Apertura y cierre de caja (corte) con fondo inicial, ventas por método
  de pago y diferencia.
- El cobro es UNA transacción atómica: venta + partidas + descuento de
  inventario por receta + movimientos, todo o nada.
- El folio es consecutivo por instalación (folio #000001, #000002, …).
"""
from __future__ import annotations

from typing import Optional

from app.core.database import Database
from app.core.services.inventory_service import consume_for_sale
from app.core.services.validators import ValidationError
from app.signals import SignalBus

# Tipos de pedido y métodos de pago (clave interna → etiqueta visible)
ORDER_TYPES = {"mesa": "Mesa", "llevar": "Para llevar", "domicilio": "A domicilio"}
PAYMENT_METHODS = {"efectivo": "Efectivo", "tarjeta": "Tarjeta", "transferencia": "Transferencia"}


class SalesService:
    """Operaciones de la caja registradora."""

    def __init__(self, db: Database, bus: SignalBus, settings):
        self.db = db
        self.bus = bus
        self.settings = settings  # SettingsManager (lee ticket.tax_rate, etc.)

    # ==================================================================
    # Sesiones de caja
    # ==================================================================

    def current_session(self) -> Optional[dict]:
        """Sesión de caja abierta (o None)."""
        return self.db.one(
            "SELECT * FROM cash_sessions WHERE status = 'abierta'"
            " ORDER BY id DESC LIMIT 1"
        )

    def get_session(self, session_id: int) -> Optional[dict]:
        return self.db.one("SELECT * FROM cash_sessions WHERE id = ?", (session_id,))

    def open_session(self, fund: float, opened_by: str = "") -> dict:
        """Abre caja con fondo inicial (puede ser 0)."""
        if self.current_session():
            raise ValidationError("Ya hay una caja abierta. Realice el corte primero.")
        fund = self._amount(fund, "El fondo inicial", allow_zero=True)
        session_id = self.db.execute(
            "INSERT INTO cash_sessions (initial_fund, opened_by) VALUES (?, ?)",
            (fund, opened_by or None),
        )
        self.bus.cashSessionChanged.emit()
        return self.get_session(session_id)  # type: ignore[return-value]

    def session_totals(self, session_id: int) -> dict:
        """Ventas de la sesión agrupadas por método de pago."""
        rows = self.db.query(
            """
            SELECT payment_method, COUNT(*) AS count, SUM(total) AS total
              FROM sales
             WHERE cash_session_id = ?
             GROUP BY payment_method
            """,
            (session_id,),
        )
        methods = {
            row["payment_method"]: {"count": row["count"], "total": row["total"] or 0}
            for row in rows
        }
        grand_total = sum(m["total"] for m in methods.values())
        grand_count = sum(m["count"] for m in methods.values())
        return {"methods": methods, "grand_total": grand_total, "grand_count": grand_count}

    def close_session(self, session_id: int, counted: float, closed_by: str = "",
                      note: str = "") -> dict:
        """Cierra la caja calculando lo esperado y la diferencia.

        Esperado en efectivo = fondo inicial + ventas en efectivo.
        Devuelve un resumen para mostrar en la UI del corte.
        """
        session = self.get_session(session_id)
        if session is None or session["status"] != "abierta":
            raise ValidationError("La caja ya está cerrada.")

        counted = self._amount(counted, "El conteo de efectivo")
        totals = self.session_totals(session_id)
        cash_expected = round(
            session["initial_fund"] + totals["methods"].get("efectivo", {}).get("total", 0), 2
        )
        difference = round(counted - cash_expected, 2)

        self.db.execute(
            """
            UPDATE cash_sessions
               SET closed_at = datetime('now', 'localtime'), counted = ?,
                   expected = ?, difference = ?, status = 'cerrada',
                   closed_by = ?, note = ?
             WHERE id = ?
            """,
            (counted, cash_expected, difference, closed_by or None,
             (note or "").strip() or None, session_id),
        )
        self.bus.cashSessionChanged.emit()

        return {
            "session": self.get_session(session_id),
            "totals": totals,
            "cash_expected": cash_expected,
            "counted": counted,
            "difference": difference,
        }

    def list_sessions(self, limit: int = 50) -> list[dict]:
        return self.db.query(
            "SELECT * FROM cash_sessions ORDER BY id DESC LIMIT ?", (limit,)
        )

    # ==================================================================
    # Cobro (checkout)
    # ==================================================================

    def checkout(
        self,
        items: list[dict],
        order_type: str,
        payment_method: str,
        discount: float = 0.0,
        tip: float = 0.0,
        paid: Optional[float] = None,
        waiter: str = "",
        customer: str = "",
        note: str = "",
    ) -> dict:
        """Registra la venta, descuenta inventario y devuelve el comprobante.

        `items`: [{"product_id", "name", "unit_price", "quantity", "note"}]
        Devuelve {"sale", "items", "low_stock"} — `low_stock` es la lista de
        insumos que quedaron en/bajo su mínimo tras la venta.
        """
        if not items:
            raise ValidationError("El carrito está vacío.")
        if order_type not in ORDER_TYPES:
            raise ValidationError("Tipo de pedido inválido.")
        if payment_method not in PAYMENT_METHODS:
            raise ValidationError("Método de pago inválido.")

        session = self.current_session()
        if session is None:
            raise ValidationError("No hay caja abierta. Abra la caja para vender.")

        discount = self._amount(discount, "El descuento", allow_zero=True)
        tip = self._amount(tip, "La propina", allow_zero=True)

        subtotal = round(sum(float(i["unit_price"]) * float(i["quantity"]) for i in items), 2)
        if discount > subtotal:
            raise ValidationError("El descuento no puede ser mayor al subtotal.")

        tax_rate = float(self.settings.get("ticket.tax_rate", 0) or 0)
        taxable = round(subtotal - discount, 2)
        tax = round(taxable * tax_rate / 100.0, 2)
        total = round(taxable + tax + tip, 2)

        if paid is None:
            paid = total
        paid = self._amount(paid, "El pago recibido", allow_zero=True)
        if payment_method == "efectivo" and paid + 1e-9 < total:
            raise ValidationError("El pago en efectivo es menor que el total.")
        change = round(max(paid - total, 0.0), 2)

        low_stock: list[str] = []
        with self.db.transaction():
            # Folio consecutivo dentro de la transacción (sin carreras)
            folio = self.db.one("SELECT COALESCE(MAX(folio), 0) + 1 AS f FROM sales")["f"]
            sale_id = self.db.execute(
                """
                INSERT INTO sales
                    (folio, order_type, payment_method, subtotal, discount, tax,
                     tip, total, paid, change, waiter, customer, note,
                     cash_session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    folio, order_type, payment_method, subtotal, discount, tax,
                    tip, total, paid, change, (waiter or "").strip() or None,
                    (customer or "").strip() or None, (note or "").strip() or None,
                    session["id"],
                ),
            )
            # Partidas de la venta
            for item in items:
                self.db.execute(
                    """
                    INSERT INTO sale_items
                        (sale_id, product_id, product_name, unit_price, quantity,
                         note, line_total)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sale_id,
                        item.get("product_id"),
                        item["name"],
                        round(float(item["unit_price"]), 2),
                        float(item["quantity"]),
                        (item.get("note") or "").strip() or None,
                        round(float(item["unit_price"]) * float(item["quantity"]), 2),
                    ),
                )
                # Descuento de inventario por receta: PEPS/FEFO con lotes y
                # registro en el kardex (consumo por venta), en la misma
                # transacción atómica del cobro.
                product_id = item.get("product_id")
                if product_id:
                    recipe = self.db.query(
                        """
                        SELECT r.ingredient_id, r.quantity
                          FROM recipes r JOIN ingredients i ON i.id = r.ingredient_id
                         WHERE r.product_id = ?
                        """,
                        (product_id,),
                    )
                    for row in recipe:
                        consumed = row["quantity"] * float(item["quantity"])
                        result = consume_for_sale(
                            self.db, row["ingredient_id"], consumed, sale_id, folio
                        )
                        if result["is_low"]:
                            low_stock.append(result["ingredient_name"])

        self.bus.salesChanged.emit()
        self.bus.ingredientsChanged.emit()
        self.bus.movementsChanged.emit()

        return {
            "sale": self.get_sale(sale_id),
            "items": self.get_sale_items(sale_id),
            "low_stock": low_stock,
        }

    # ==================================================================
    # Consulta de ventas
    # ==================================================================

    def get_sale(self, sale_id: int) -> Optional[dict]:
        return self.db.one("SELECT * FROM sales WHERE id = ?", (sale_id,))

    def get_sale_items(self, sale_id: int) -> list[dict]:
        return self.db.query(
            "SELECT * FROM sale_items WHERE sale_id = ? ORDER BY id", (sale_id,)
        )

    def list_sales(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """Ventas en un rango de fechas (formato 'YYYY-MM-DD', inclusivo)."""
        sql = "SELECT * FROM sales WHERE 1 = 1"
        params: list = []
        if date_from:
            sql += " AND date(datetime) >= date(?)"
            params.append(date_from)
        if date_to:
            sql += " AND date(datetime) <= date(?)"
            params.append(date_to)
        sql += " ORDER BY datetime DESC, id DESC LIMIT ?"
        params.append(limit)
        return self.db.query(sql, tuple(params))

    def recent_sales(self, limit: int = 100) -> list[dict]:
        return self.db.query(
            "SELECT * FROM sales ORDER BY datetime DESC, id DESC LIMIT ?", (limit,)
        )

    # ------------------------------------------------------------------
    # Validación numérica
    # ------------------------------------------------------------------

    @staticmethod
    def _amount(value: float, label: str, allow_zero: bool = False) -> float:
        try:
            amount = float(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{label} debe ser un número.") from exc
        if amount < 0:
            raise ValidationError(f"{label} no puede ser negativo.")
        if not allow_zero and amount == 0:
            raise ValidationError(f"{label} debe ser mayor a 0.")
        return round(amount, 2)
