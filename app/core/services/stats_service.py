"""Servicio de ESTADÍSTICAS: agregados de ventas para gráficas y reportes.

Produce series listas para QtCharts:
- Ventas por día / por hora / por método de pago.
- Productos más vendidos (por cantidad y por importe).
- KPIs: total vendido, número de tickets, ticket promedio, propinas.
"""
from __future__ import annotations

from app.core.database import Database


class StatsService:
    """Consultas agregadas sobre la tabla de ventas."""

    def __init__(self, db: Database, settings=None):
        self.db = db
        self.settings = settings

    def summary(self, date_from: str, date_to: str) -> dict:
        """Resumen completo entre dos fechas ('YYYY-MM-DD', inclusivo)."""
        cond = "WHERE date(datetime) >= date(?) AND date(datetime) <= date(?)"
        args = (date_from, date_to)
        # El detalle de partidas se une con la venta: el filtro apunta a s.datetime
        cond_items = cond.replace("datetime", "s.datetime")

        totals_row = self.db.one(
            f"""
            SELECT COALESCE(SUM(total), 0)    AS total_sales,
                   COUNT(*)                   AS ticket_count,
                   COALESCE(SUM(tip), 0)      AS tips,
                   COALESCE(SUM(tax), 0)      AS taxes,
                   COALESCE(SUM(discount), 0) AS discounts
              FROM sales {cond}
            """,
            args,
        ) or {}

        items_row = self.db.one(
            f"""
            SELECT COALESCE(SUM(si.quantity), 0) AS items_sold
              FROM sale_items si
              JOIN sales s ON s.id = si.sale_id
            {cond_items}
            """,
            args,
        ) or {}

        ticket_count = int(totals_row.get("ticket_count") or 0)
        total_sales = float(totals_row.get("total_sales") or 0)
        avg_ticket = round(total_sales / ticket_count, 2) if ticket_count else 0.0

        return {
            "date_from": date_from,
            "date_to": date_to,
            "kpi": {
                "total_sales": total_sales,
                "ticket_count": ticket_count,
                "avg_ticket": avg_ticket,
                "items_sold": int(items_row.get("items_sold") or 0),
                "tips": float(totals_row.get("tips") or 0),
                "taxes": float(totals_row.get("taxes") or 0),
                "discounts": float(totals_row.get("discounts") or 0),
            },
            "by_day": self._grouped(
                f"SELECT substr(datetime, 1, 10) AS bucket,"
                f" COUNT(*) AS count, SUM(total) AS total"
                f" FROM sales {cond} GROUP BY bucket ORDER BY bucket",
                args,
            ),
            "by_hour": self._grouped(
                f"SELECT strftime('%H', datetime) AS bucket,"
                f" COUNT(*) AS count, SUM(total) AS total"
                f" FROM sales {cond} GROUP BY bucket ORDER BY bucket",
                args,
            ),
            "by_method": self._grouped(
                f"SELECT payment_method AS bucket,"
                f" COUNT(*) AS count, SUM(total) AS total"
                f" FROM sales {cond} GROUP BY bucket ORDER BY total DESC",
                args,
            ),
            "by_order_type": self._grouped(
                f"SELECT order_type AS bucket,"
                f" COUNT(*) AS count, SUM(total) AS total"
                f" FROM sales {cond} GROUP BY bucket ORDER BY total DESC",
                args,
            ),
            "top_products": self.db.query(
                f"""
                SELECT si.product_name AS name,
                       SUM(si.quantity) AS quantity,
                       SUM(si.line_total) AS revenue
                  FROM sale_items si
                  JOIN sales s ON s.id = si.sale_id
                {cond_items}
                 GROUP BY si.product_name
                 ORDER BY quantity DESC
                 LIMIT 10
                """,
                args,
            ),
        }

    def sales_rows(self, date_from: str, date_to: str) -> list[dict]:
        """Filas planas de ventas del rango, para exportar a CSV/Excel."""
        return self.db.query(
            """
            SELECT folio, datetime, order_type, payment_method, waiter, customer,
                   subtotal, discount, tax, tip, total, paid, change
              FROM sales
             WHERE date(datetime) >= date(?) AND date(datetime) <= date(?)
             ORDER BY datetime
            """,
            (date_from, date_to),
        )

    # ==================================================================
    # Almacén: valor, caducidades, estancados y merma
    # ==================================================================

    def warehouse_summary(self, date_from: str, date_to: str) -> dict:
        """Indicadores y series de almacén para el módulo Estadísticas."""
        default_warn = int(self._setting("inventory.expiry_warning_days", 7))
        stale_days = int(self._setting("inventory.stale_days", 30))

        value_row = self.db.one(
            "SELECT COALESCE(SUM(stock * cost), 0) AS v,"
            " COUNT(*) AS n FROM ingredients"
        ) or {}
        low_row = self.db.one(
            """
            SELECT COUNT(*) AS n FROM ingredients
             WHERE stock <= 0 OR (min_stock > 0 AND stock <= min_stock)
            """
        ) or {}

        # Caducidades sobre lotes activos con fecha
        lots = self.db.query(
            """
            SELECT l.expiration_date, l.quantity,
                   CAST(julianday(l.expiration_date) - julianday('now') AS INTEGER)
                       AS days_left,
                   CASE WHEN i.warning_days > 0 THEN i.warning_days ELSE ? END
                       AS warn_days
              FROM lots l JOIN ingredients i ON i.id = l.ingredient_id
             WHERE l.quantity > 0 AND l.expiration_date IS NOT NULL
            """,
            (default_warn,),
        )
        expired = sum(1 for lot in lots if lot["days_left"] < 0)
        expiring = sum(1 for lot in lots
                       if 0 <= lot["days_left"] <= int(lot["warn_days"]))

        stale_row = self.db.one(
            """
            SELECT COUNT(*) AS n, COALESCE(SUM(i.stock * i.cost), 0) AS v
              FROM ingredients i
             WHERE i.stock > 0
               AND NOT EXISTS (
                    SELECT 1 FROM movements m
                     WHERE m.ingredient_id = i.id
                       AND m.type IN ('salida', 'merma', 'venta'))
               -- el insumo debe existir desde antes de la ventana para ser
               -- considerado "sin movimiento" (anclada a su primer movimiento)
               AND COALESCE(
                    (SELECT MIN(date(m.datetime)) FROM movements m
                      WHERE m.ingredient_id = i.id),
                    date('now')) <= date('now', ?)
            """,
            (f"-{stale_days} days",),
        ) or {}

        merma_row = self.db.one(
            """
            SELECT COALESCE(SUM(ABS(m.quantity)
                               * COALESCE(m.unit_cost, i.cost, 0)), 0) AS v,
                   COUNT(*) AS n
              FROM movements m
              JOIN ingredients i ON i.id = m.ingredient_id
             WHERE m.type = 'merma'
               AND date(m.datetime) >= date(?) AND date(m.datetime) <= date(?)
            """,
            (date_from, date_to),
        ) or {}

        return {
            "inventory_value": round(float(value_row.get("v") or 0), 2),
            "ingredient_count": int(value_row.get("n") or 0),
            "low_count": int(low_row.get("n") or 0),
            "expired_count": expired,
            "expiring_count": expiring,
            "stale_count": int(stale_row.get("n") or 0),
            "stale_value": round(float(stale_row.get("v") or 0), 2),
            "merma_value": round(float(merma_row.get("v") or 0), 2),
            "merma_count": int(merma_row.get("n") or 0),
            # Series para las gráficas de almacén
            "merma_by_reason": self._grouped(
                """
                SELECT COALESCE(NULLIF(TRIM(m.reason), ''), 'Sin motivo') AS bucket,
                       COUNT(*) AS count,
                       SUM(ABS(m.quantity) * COALESCE(m.unit_cost, i.cost, 0))
                           AS total
                  FROM movements m
                  JOIN ingredients i ON i.id = m.ingredient_id
                 WHERE m.type = 'merma'
                   AND date(m.datetime) >= date(?) AND date(m.datetime) <= date(?)
                 GROUP BY bucket ORDER BY total DESC LIMIT 10
                """,
                (date_from, date_to),
            ),
            "consumption_by_ingredient": self._grouped(
                """
                SELECT i.name AS bucket,
                       COUNT(*) AS count,
                       SUM(ABS(m.quantity)) AS quantity,
                       SUM(ABS(m.quantity) * COALESCE(m.unit_cost, i.cost, 0))
                           AS total
                  FROM movements m
                  JOIN ingredients i ON i.id = m.ingredient_id
                 WHERE m.type = 'venta'
                   AND date(m.datetime) >= date(?) AND date(m.datetime) <= date(?)
                 GROUP BY i.name ORDER BY quantity DESC LIMIT 8
                """,
                (date_from, date_to),
            ),
            "movements_by_day": self._grouped(
                """
                SELECT substr(m.datetime, 1, 10) AS bucket,
                       COUNT(*) AS count, 0 AS total
                  FROM movements m
                 WHERE date(m.datetime) >= date(?) AND date(m.datetime) <= date(?)
                 GROUP BY bucket ORDER BY bucket
                """,
                (date_from, date_to),
            ),
        }

    def _setting(self, key: str, default):
        try:
            if self.settings is None:
                return default
            return self.settings.get(key, default)
        except (AttributeError, TypeError):
            return default

    # ------------------------------------------------------------------

    def _grouped(self, sql: str, args: tuple) -> list[dict]:
        """Ejecuta una consulta agrupada y normaliza valores nulos."""
        rows = self.db.query(sql, args)
        for row in rows:
            row["total"] = float(row.get("total") or 0)
            row["count"] = int(row.get("count") or 0)
        return rows
