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

    # ------------------------------------------------------------------

    def _grouped(self, sql: str, args: tuple) -> list[dict]:
        """Ejecuta una consulta agrupada y normaliza valores nulos."""
        rows = self.db.query(sql, args)
        for row in rows:
            row["total"] = float(row.get("total") or 0)
            row["count"] = int(row.get("count") or 0)
        return rows
