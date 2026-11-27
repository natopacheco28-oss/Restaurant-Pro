"""Módulo ESTADÍSTICAS: gráficas Fluent y exportación.

- Ventas por día / semana / mes con filtro por rango de fechas (preajustes
  o fechas personalizadas).
- KPIs: total vendido, tickets, ticket promedio, artículos vendidos, propinas.
- Gráficas QtCharts (PySide6-Addons) que siguen el tema claro/oscuro.
- Exportación a Excel (openpyxl, multi-hoja) y CSV.
Si QtCharts no está disponible, las tarjetas muestran tablas de texto.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from typing import Optional

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SimpleCardWidget,
    TitleLabel,
)

# QtCharts puede no estar instalado: se degrada con elegancia
try:
    from PySide6.QtCharts import (
        QBarCategoryAxis,
        QBarSeries,
        QBarSet,
        QChart,
        QChartView,
        QPieSeries,
        QValueAxis,
    )
    HAS_CHARTS = True
except ImportError:  # pragma: no cover
    HAS_CHARTS = False

from qfluentwidgets import isDarkTheme, qconfig

from app.printing.ticket_builder import money
from app.ui.common import COLOR_ERROR, COLOR_WARN, KPICard, currency_of, fi

# Presets del filtro de fechas
PRESETS = ["Hoy", "Ayer", "Últimos 7 días", "Esta semana", "Este mes",
           "Mes pasado", "Personalizado"]


def _range_for(preset: str) -> tuple[date, date]:
    """Convierte un preajuste en (fecha_inicio, fecha_fin)."""
    today = date.today()
    if preset == "Hoy":
        return today, today
    if preset == "Ayer":
        return today - timedelta(days=1), today - timedelta(days=1)
    if preset == "Últimos 7 días":
        return today - timedelta(days=6), today
    if preset == "Esta semana":
        return today - timedelta(days=today.weekday()), today
    if preset == "Este mes":
        return today.replace(day=1), today
    if preset == "Mes pasado":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    return today, today  # Personalizado (se ajusta en UI)


class StatsModule(QWidget):
    """Página de estadísticas."""

    def __init__(self, ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("StatsModule")
        self._summary: dict = {}
        self._build_ui()
        self.refresh()

        self.ctx.bus.salesChanged.connect(self.refresh)
        qconfig.themeChanged.connect(self.refresh)  # reestilizar al cambiar tema

    # ==================================================================
    # UI
    # ==================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)
        root.addWidget(TitleLabel("Estadísticas"))

        # ---------------- Filtros ----------------
        filter_card = SimpleCardWidget()
        filter_row = QHBoxLayout(filter_card)
        filter_row.setContentsMargins(16, 10, 16, 10)
        filter_row.setSpacing(10)

        filter_row.addWidget(CaptionLabel("Periodo:"))
        self._preset_combo = ComboBox()
        self._preset_combo.addItems(PRESETS)
        self._preset_combo.setCurrentIndex(0)
        self._preset_combo.currentIndexChanged.connect(self._on_preset)
        filter_row.addWidget(self._preset_combo)

        filter_row.addWidget(CaptionLabel("Desde:"))
        self._date_from = self._make_date_picker()
        filter_row.addWidget(self._date_from)
        filter_row.addWidget(CaptionLabel("Hasta:"))
        self._date_to = self._make_date_picker()
        filter_row.addWidget(self._date_to)

        self._date_from.setEnabled(False)
        self._date_to.setEnabled(False)

        refresh_button = PushButton("Actualizar")
        refresh_button.setIcon(fi("SYNC", "UPDATE", "CARE_RIGHT_SOLID"))
        refresh_button.clicked.connect(self.refresh)
        filter_row.addWidget(refresh_button)
        filter_row.addStretch(1)

        export_csv = PushButton("Exportar CSV")
        export_csv.setIcon(fi("DOCUMENT", "SAVE"))
        export_csv.clicked.connect(self._export_csv)
        filter_row.addWidget(export_csv)

        export_excel = PrimaryPushButton("Exportar Excel")
        export_excel.setIcon(fi("SAVE_AS", "SAVE", "DOCUMENT"))
        export_excel.clicked.connect(self._export_excel)
        filter_row.addWidget(export_excel)
        root.addWidget(filter_card)

        # ---------------- KPIs de ventas ----------------
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self._kpi_total = KPICard("Ventas totales")
        self._kpi_tickets = KPICard("Tickets")
        self._kpi_avg = KPICard("Ticket promedio")
        self._kpi_items = KPICard("Artículos vendidos")
        self._kpi_tips = KPICard("Propinas")
        for card in (self._kpi_total, self._kpi_tickets, self._kpi_avg,
                     self._kpi_items, self._kpi_tips):
            kpi_row.addWidget(card, 1)
        root.addLayout(kpi_row)

        # ---------------- KPIs de almacén ----------------
        warehouse_row = QHBoxLayout()
        warehouse_row.setSpacing(12)
        self._w_value = KPICard("Valor del inventario")
        self._w_low = KPICard("Insumos en stock bajo")
        self._w_expiring = KPICard("Por caducar / vencidos")
        self._w_merma = KPICard("Merma del periodo")
        self._w_stale = KPICard("Valor inmovilizado")
        for card in (self._w_value, self._w_low, self._w_expiring,
                     self._w_merma, self._w_stale):
            warehouse_row.addWidget(card, 1)
        root.addLayout(warehouse_row)

        # ---------------- Gráficas ----------------
        charts_grid = QGridLayout()
        charts_grid.setSpacing(12)
        self._charts: dict[str, QWidget] = {}
        self._chart_layouts: dict[str, QVBoxLayout] = {}
        positions = {
            "by_day": (0, 0), "by_hour": (0, 1),
            "by_method": (1, 0), "top_products": (1, 1),
        }
        titles = {
            "by_day": "Ventas por día",
            "by_hour": "Ventas por hora",
            "by_method": "Ventas por método de pago",
            "top_products": "Productos más vendidos",
        }
        for key, (row, col) in positions.items():
            card = SimpleCardWidget()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 12)
            card_layout.addWidget(TitleLabel(titles[key]))
            placeholder = BodyLabel("Sin datos en el periodo")
            card_layout.addWidget(placeholder, 1)
            self._charts[key] = placeholder
            self._chart_layouts[key] = card_layout
            charts_grid.addWidget(card, row, col)
        root.addLayout(charts_grid, 1)

        # ---------------- Gráficas de almacén ----------------
        warehouse_grid = QGridLayout()
        warehouse_grid.setSpacing(12)
        w_positions = {
            "w_merma": (0, 0), "w_consumo": (0, 1), "w_movs": (0, 2),
        }
        w_titles = {
            "w_merma": "Merma por motivo",
            "w_consumo": "Consumo por insumo (ventas)",
            "w_movs": "Movimientos del kardex por día",
        }
        for key, (row, col) in w_positions.items():
            card = SimpleCardWidget()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 12)
            card_layout.addWidget(TitleLabel(w_titles[key]))
            placeholder = BodyLabel("Sin datos en el periodo")
            card_layout.addWidget(placeholder, 1)
            self._charts[key] = placeholder
            self._chart_layouts[key] = card_layout
            warehouse_grid.addWidget(card, row, col)
        root.addLayout(warehouse_grid, 1)

    def _make_date_picker(self):
        """CalendarPicker de qfluentwidgets; QDateEdit de respaldo."""
        try:
            from qfluentwidgets import CalendarPicker

            picker = CalendarPicker()
            self._picker_set_date(picker, date.today())
            return picker
        except ImportError:  # pragma: no cover
            from PySide6.QtWidgets import QDateEdit

            picker = QDateEdit()
            picker.setCalendarPopup(True)
            return picker

    def _picker_date(self, picker) -> date:
        value = picker.getDate()
        return date(value.year(), value.month(), value.day())

    def _picker_set_date(self, picker, value: date) -> None:
        from PySide6.QtCore import QDate

        # value es un datetime.date: year/month/day son atributos, no métodos
        picker.setDate(QDate(value.year, value.month, value.day))

    # ==================================================================
    # Carga de datos
    # ==================================================================

    def _current_range(self) -> tuple[date, date]:
        preset = PRESETS[self._preset_combo.currentIndex()]
        if preset == "Personalizado":
            return self._picker_date(self._date_from), self._picker_date(self._date_to)
        return _range_for(preset)

    def _on_preset(self, index: int) -> None:
        custom = PRESETS[index] == "Personalizado"
        self._date_from.setEnabled(custom)
        self._date_to.setEnabled(custom)
        if not custom:
            start, end = _range_for(PRESETS[index])
            self._picker_set_date(self._date_from, start)
            self._picker_set_date(self._date_to, end)
        self.refresh()

    def refresh(self) -> None:
        """Recalcula KPIs y gráficas (ventas y almacén) del periodo."""
        start, end = self._current_range()
        self._summary = self.ctx.stats.summary(start.isoformat(), end.isoformat())
        self._warehouse = self.ctx.stats.warehouse_summary(
            start.isoformat(), end.isoformat())
        kpi = self._summary["kpi"]
        currency = currency_of(self.ctx.settings)

        self._kpi_total.set_value(money(kpi["total_sales"], currency))
        self._kpi_tickets.set_value(str(kpi["ticket_count"]))
        self._kpi_avg.set_value(money(kpi["avg_ticket"], currency))
        self._kpi_items.set_value(str(kpi["items_sold"]))
        self._kpi_tips.set_value(money(kpi["tips"], currency))

        self._render_warehouse_kpis(currency)
        self._render_charts()

    def _render_warehouse_kpis(self, currency: str) -> None:
        warehouse = getattr(self, "_warehouse", None) or {}
        self._w_value.set_value(money(warehouse.get("inventory_value", 0), currency))
        self._w_value.set_value_color(None)
        low = warehouse.get("low_count", 0)
        self._w_low.set_value(str(low))
        self._w_low.set_value_color(COLOR_WARN if low else None)
        expired = warehouse.get("expired_count", 0)
        expiring = warehouse.get("expiring_count", 0)
        self._w_expiring.set_value(f"{expiring} / {expired}")
        self._w_expiring.set_value_color(
            COLOR_ERROR if expired else COLOR_WARN if expiring else None)
        self._w_merma.set_value(
            money(warehouse.get("merma_value", 0), currency))
        self._w_merma.set_value_color(COLOR_WARN if warehouse.get("merma_value") else None)
        self._w_stale.set_value(money(warehouse.get("stale_value", 0), currency))
        self._w_stale.set_value_color(COLOR_WARN if warehouse.get("stale_value") else None)

    # ==================================================================
    # Gráficas
    # ==================================================================

    def _render_charts(self) -> None:
        if not HAS_CHARTS:
            self._render_text_charts()
            return
        self._render_day_chart()
        self._render_hour_chart()
        self._render_method_chart()
        self._render_top_chart()
        self._render_warehouse_charts()

    def _render_warehouse_charts(self) -> None:
        """Merma por motivo (pastel), consumo por insumo y movimientos/día."""
        warehouse = getattr(self, "_warehouse", None) or {}

        # Merma por motivo → pastel
        buckets = warehouse.get("merma_by_reason") or []
        if buckets:
            view = self._make_pie_chart(buckets)
            self._replace_holder("w_merma", view)
        else:
            self._reset_holder("w_merma", "Sin merma en el periodo")

        # Consumo por insumo → barras por cantidad vendida/consumida
        consumo = warehouse.get("consumption_by_ingredient") or []
        if consumo:
            rows = [{"bucket": row["bucket"], "total": float(row["quantity"])}
                    for row in consumo]
            view = self._make_bar_chart(rows, "insumo")
            self._replace_holder("w_consumo", view)
        else:
            self._reset_holder("w_consumo", "Sin consumo de inventario en el periodo")

        # Movimientos por día → barras por número de movimientos
        movs = warehouse.get("movements_by_day") or []
        if movs:
            rows = [{"bucket": row["bucket"], "total": float(row["count"])}
                    for row in movs]
            view = self._make_bar_chart(rows, "día")
            self._replace_holder("w_movs", view)
        else:
            self._reset_holder("w_movs", "Sin movimientos en el periodo")

    def _make_pie_chart(self, buckets: list[dict]):
        """Gráfica de pastel a partir de buckets [{bucket, total}]."""
        from PySide6.QtGui import QColor

        series = QPieSeries()
        for row in buckets:
            slice_ = series.append(str(row["bucket"]), max(float(row["total"]), 0.001))
            slice_.setLabelColor(QColor("#1a1a1a"))
        chart = QChart()
        chart.addSeries(series)
        chart.legend().show()
        self._style_chart(chart)
        view = QChartView(chart)
        view.setRenderHint(_painter_antialias())
        view.setMinimumHeight(200)
        return view

    def _reset_holder(self, key: str, message: str) -> None:
        """Vuelve al placeholder de texto cuando la serie está vacía."""
        if key not in self._chart_layouts:
            return
        old = self._charts.pop(key, None)
        if old is not None:
            self._chart_layouts[key].removeWidget(old)
            old.deleteLater()
        placeholder = BodyLabel(message)
        self._charts[key] = placeholder
        self._chart_layouts[key].addWidget(placeholder, 1)

    def _style_chart(self, chart: "QChart") -> None:  # type: ignore[name-defined]
        """Estilo Fluent claro/oscuro de la gráfica."""
        from PySide6.QtGui import QColor

        dark = isDarkTheme()
        chart.setTheme(QChart.ChartTheme.ChartThemeDark if dark
                       else QChart.ChartTheme.ChartThemeLight)
        chart.setBackgroundRoundness(0)
        color = QColor("#ffffff" if dark else "#1a1a1a")
        chart.setTitleBrush(color)

    def _replace_holder(self, key: str, widget: QWidget) -> None:
        """Sustituye el placeholder por la vista de gráfica en la tarjeta."""
        old = self._charts.pop(key, None)
        if old is not None:
            self._chart_layouts[key].removeWidget(old)
            old.deleteLater()
        self._charts[key] = widget
        self._chart_layouts[key].addWidget(widget, 1)

    def _make_bar_chart(self, buckets: list[dict], title_x: str,
                        horizontal_labels: bool = True):
        """Gráfica de barras a partir de `buckets` [{bucket, total, count}]."""
        from PySide6.QtGui import QColor

        series = QBarSeries()
        bar_set = QBarSet("Ventas")
        bar_set.setColor(QColor("#ff7a1a"))
        categories = []
        for row in buckets:
            categories.append(str(row["bucket"]))
            bar_set.append(float(row["total"]))
        series.append(bar_set)

        chart = QChart()
        chart.addSeries(series)
        chart.legend().hide()

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.0f")
        max_value = max((float(r["total"]) for r in buckets), default=1)
        axis_y.setRange(0, max(max_value * 1.15, 1))
        series.attachAxis(axis_y)

        self._style_chart(chart)

        view = QChartView(chart)
        view.setRenderHint(_painter_antialias())
        view.setMinimumHeight(200)
        return view

    def _render_day_chart(self) -> None:
        buckets = self._summary["by_day"]
        if not buckets:
            return
        view = self._make_bar_chart(buckets, "día")
        # Etiquetas cortas dd/mm en el eje
        self._replace_holder("by_day", view)

    def _render_hour_chart(self) -> None:
        buckets = self._summary["by_hour"]
        if not buckets:
            return
        view = self._make_bar_chart(buckets, "hora")
        self._replace_holder("by_hour", view)

    def _render_method_chart(self) -> None:
        from app.core.services.sales_service import PAYMENT_METHODS
        from PySide6.QtGui import QColor

        buckets = self._summary["by_method"]
        if not buckets:
            return
        series = QPieSeries()
        for index, row in enumerate(buckets):
            label = PAYMENT_METHODS.get(row["bucket"], str(row["bucket"]))
            slice_ = series.append(label, float(row["total"]))
            slice_.setLabelColor(QColor("#1a1a1a"))
        chart = QChart()
        chart.addSeries(series)
        chart.legend().show()
        self._style_chart(chart)
        view = QChartView(chart)
        view.setRenderHint(_painter_antialias())
        view.setMinimumHeight(200)
        self._replace_holder("by_method", view)

    def _render_top_chart(self) -> None:
        buckets = [{"bucket": row["name"], "total": float(row["quantity"])}
                   for row in self._summary["top_products"]]
        if not buckets:
            return
        view = self._make_bar_chart(buckets, "producto")
        self._replace_holder("top_products", view)

    def _render_text_charts(self) -> None:
        """Respaldo sin QtCharts: muestra los datos como texto."""
        for key in ("by_day", "by_hour", "by_method", "top_products",
                    "w_merma", "w_consumo", "w_movs"):
            if key.startswith("w_"):
                source = getattr(self, "_warehouse", None) or {}
                mapping = {"w_merma": "merma_by_reason",
                           "w_consumo": "consumption_by_ingredient",
                           "w_movs": "movements_by_day"}
                rows = source.get(mapping[key], [])
            else:
                rows = self._summary.get(key, [])
            lines = []
            for row in rows[:8]:
                if "name" in row:
                    lines.append(f"· {row['name']}: {row['quantity']:g} vendidos")
                elif key == "w_consumo":
                    lines.append(f"· {row['bucket']}: {row['quantity']:g} consumidos")
                elif key == "w_movs":
                    lines.append(f"· {row['bucket']}: {row['count']} movimiento(s)")
                else:
                    label = row["bucket"]
                    lines.append(f"· {label}: {money(row['total'], currency_of(self.ctx.settings))}")
            widget = self._charts.get(key)
            if widget is not None:
                widget.setText("\n".join(lines) or "Sin datos en el periodo")

    # ==================================================================
    # Exportación
    # ==================================================================

    def _export_csv(self) -> None:
        """Exporta las ventas del periodo a CSV."""
        start, end = self._current_range()
        path, _ = self._save_dialog(
            "Exportar ventas a CSV",
            f"RestaurantePro_ventas_{start}_{end}.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        rows = self.ctx.stats.sales_rows(start.isoformat(), end.isoformat())
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            headers = ["Folio", "Fecha", "Pedido", "Método", "Mesero", "Cliente",
                       "Subtotal", "Descuento", "Impuesto", "Propina", "Total",
                       "Pagado", "Cambio"]
            writer.writerow(headers)
            from app.core.services.sales_service import ORDER_TYPES, PAYMENT_METHODS

            for row in rows:
                writer.writerow([
                    row["folio"], row["datetime"],
                    ORDER_TYPES.get(row["order_type"], row["order_type"]),
                    PAYMENT_METHODS.get(row["payment_method"], row["payment_method"]),
                    row["waiter"] or "", row["customer"] or "",
                    row["subtotal"], row["discount"], row["tax"], row["tip"],
                    row["total"], row["paid"], row["change"],
                ])
        self._exported(path)

    def _export_excel(self) -> None:
        """Exporta el reporte multi-hoja a Excel con openpyxl."""
        try:
            import openpyxl
            from openpyxl.styles import Font
        except ImportError:
            InfoBar.warning(title="openpyxl no instalado",
                            content="Instale openpyxl para exportar a Excel; use CSV como alternativa.",
                            parent=self, position=InfoBarPosition.TOP, duration=5000)
            return

        start, end = self._current_range()
        path, _ = self._save_dialog(
            "Exportar reporte a Excel",
            f"RestaurantePro_reporte_{start}_{end}.xlsx",
            "Excel (*.xlsx)",
        )
        if not path:
            return

        summary = self._summary or self.ctx.stats.summary(
            start.isoformat(), end.isoformat())
        kpi = summary["kpi"]
        bold = Font(bold=True)

        workbook = openpyxl.Workbook()

        # Hoja 1: resumen
        sheet = workbook.active
        sheet.title = "Resumen"
        sheet.append(["Reporte de ventas", f"{start} a {end}"])
        sheet.append([])
        for label, key in (("Ventas totales", "total_sales"),
                           ("Tickets", "ticket_count"),
                           ("Ticket promedio", "avg_ticket"),
                           ("Artículos vendidos", "items_sold"),
                           ("Propinas", "tips"),
                           ("Impuestos", "taxes"),
                           ("Descuentos", "discounts")):
            sheet.append([label, kpi[key]])

        def add_series_sheet(name: str, rows: list[dict], headers: list[str]):
            ws = workbook.create_sheet(name)
            ws.append(headers)
            for cell in ws[1]:
                cell.font = bold
            for row in rows:
                if "name" in row:
                    ws.append([row["name"], row["quantity"], row["revenue"]])
                else:
                    ws.append([row["bucket"], row["count"], row["total"]])
            ws.column_dimensions["A"].width = 28
            ws.column_dimensions["B"].width = 14
            ws.column_dimensions["C"].width = 14

        add_series_sheet("Por día", summary["by_day"], ["Día", "Tickets", "Total"])
        add_series_sheet("Por hora", summary["by_hour"], ["Hora", "Tickets", "Total"])
        add_series_sheet("Por método", summary["by_method"], ["Método", "Tickets", "Total"])
        add_series_sheet("Top productos", summary["top_products"],
                         ["Producto", "Cantidad", "Ingresos"])

        # Hoja de ventas individuales
        rows = self.ctx.stats.sales_rows(start.isoformat(), end.isoformat())
        ws = workbook.create_sheet("Ventas")
        headers = ["Folio", "Fecha", "Pedido", "Método", "Mesero", "Cliente",
                   "Subtotal", "Descuento", "Impuesto", "Propina", "Total",
                   "Pagado", "Cambio"]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = bold
        from app.core.services.sales_service import ORDER_TYPES, PAYMENT_METHODS

        for row in rows:
            ws.append([
                row["folio"], row["datetime"],
                ORDER_TYPES.get(row["order_type"], row["order_type"]),
                PAYMENT_METHODS.get(row["payment_method"], row["payment_method"]),
                row["waiter"] or "", row["customer"] or "",
                row["subtotal"], row["discount"], row["tax"], row["tip"],
                row["total"], row["paid"], row["change"],
            ])
        ws.column_dimensions["B"].width = 22

        workbook.save(path)
        self._exported(path)

    # ------------------------------------------------------------------

    def _save_dialog(self, title: str, default_name: str, pattern: str) -> tuple[str, str]:
        from PySide6.QtWidgets import QFileDialog

        return QFileDialog.getSaveFileName(self, title, default_name, pattern)

    def _exported(self, path: str) -> None:
        InfoBar.success(title="Exportación completada", content=str(path),
                        parent=self, position=InfoBarPosition.TOP, duration=4000)


def _painter_antialias():
    """QPainter.Antialiasing (import local para mantener el módulo ligero)."""
    from PySide6.QtGui import QPainter

    return QPainter.RenderHint.Antialiasing
