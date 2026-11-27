"""Diálogos de tickets: vista previa, prueba de impresión y reimpresión.

- `TicketPreviewDialog`: muestra el texto EXACTO que saldrá por la
  impresora (ancho 32 o 48 caracteres) con botón Imprimir.
- `SalesHistoryDialog`: lista de tickets anteriores para reimprimir.
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QWidget,
)

from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    SubtitleLabel,
)

from app.core.services.sales_service import ORDER_TYPES, PAYMENT_METHODS
from app.printing.ticket_builder import build_ticket_text, money
from app.ui.common import currency_of, format_dt


class TicketPreviewDialog(MessageBoxBase):
    """Vista previa del ticket antes de imprimir."""

    def __init__(self, ctx, sale: dict, items: list[dict], parent: QWidget):
        super().__init__(parent)
        self.ctx = ctx
        self.sale = sale
        self.items = items

        width = int(ctx.settings.get("ticket.width_chars", 48))
        self.ticket_text = build_ticket_text(sale, items, ctx.settings, width)

        self.viewLayout.addWidget(SubtitleLabel("Vista previa del ticket"))
        self.viewLayout.addWidget(CaptionLabel(
            f"Papel {'58 mm' if width == 32 else '80 mm'} · {width} caracteres"
        ))

        from PySide6.QtWidgets import QPlainTextEdit

        self._preview = QPlainTextEdit()
        self._preview.setPlainText(self.ticket_text)
        self._preview.setReadOnly(True)
        self._preview.setFont(QFont("Consolas", 10))
        self._preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._preview.setMinimumSize(360, 420)
        self.viewLayout.addWidget(self._preview)

        self.yesButton.setText("Imprimir")
        self.cancelButton.setText("Cerrar")

    def validate(self) -> bool:
        """Imprime el ticket al confirmar."""
        logo_path = None
        if self.ctx.settings.get("ticket.show_logo", True):
            from app.core.paths import logo_asset_path, resolve_portable

            custom = self.ctx.settings.get("restaurant.logo_path", "")
            candidate = resolve_portable(custom) if custom else logo_asset_path()
            if candidate.exists():
                logo_path = str(candidate)

        ok, message = self.ctx.printer.print_sale_ticket(self.ticket_text, logo_path)
        if ok:
            InfoBar.success(title="Ticket enviado", content=message,
                            parent=self.window(), position=InfoBarPosition.TOP,
                            duration=3000)
        else:
            InfoBar.error(title="Error de impresión", content=message,
                          parent=self.window(), position=InfoBarPosition.TOP,
                          duration=6000)
        return ok


class SalesHistoryDialog(MessageBoxBase):
    """Historial de tickets anteriores con reimpresión."""

    def __init__(self, ctx, parent: QWidget):
        super().__init__(parent)
        self.ctx = ctx
        self.currency = currency_of(ctx.settings)

        self.viewLayout.addWidget(SubtitleLabel("Tickets anteriores"))
        self.viewLayout.addWidget(CaptionLabel(
            "Seleccione un ticket y pulse «Reimprimir»."
        ))

        # Filtro rápido por periodo
        filter_row = QHBoxLayout()
        self._range_combo = QComboBox()
        self._range_combo.addItems(["Hoy", "Últimos 7 días", "Últimos 30 días", "Todas"])
        self._range_combo.currentIndexChanged.connect(self._reload)
        filter_row.addWidget(self._range_combo)
        filter_row.addStretch(1)
        self.viewLayout.addLayout(filter_row)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Folio", "Fecha", "Pedido", "Método", "Total"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setFrameShape(QTableWidget.Shape.NoFrame)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._table.setMinimumSize(520, 300)
        self._table.doubleClicked.connect(lambda _: self._reprint())
        self.viewLayout.addWidget(self._table)

        self.yesButton.setText("Reimprimir")
        self.cancelButton.setText("Cerrar")
        self.widget.setMinimumWidth(560)

        self._reload()

    # ------------------------------------------------------------------

    def _reload(self) -> None:
        days = {0: 1, 1: 7, 2: 30}.get(self._range_combo.currentIndex())
        sales = self.ctx.sales.recent_sales(300)
        if days:
            from datetime import date, timedelta

            cutoff = (date.today() - timedelta(days=days)).isoformat()
            sales = [s for s in sales if str(s["datetime"])[:10] >= cutoff]

        self._sales = sales
        self._table.setRowCount(len(sales))
        for row, sale in enumerate(sales):
            self._table.setItem(row, 0, QTableWidgetItem(f"#{sale['folio']:06d}"))
            self._table.setItem(row, 1, QTableWidgetItem(format_dt(sale["datetime"])))
            self._table.setItem(row, 2, QTableWidgetItem(
                ORDER_TYPES.get(sale["order_type"], sale["order_type"])))
            self._table.setItem(row, 3, QTableWidgetItem(
                PAYMENT_METHODS.get(sale["payment_method"], sale["payment_method"])))
            self._table.setItem(row, 4, QTableWidgetItem(
                money(sale["total"], self.currency)))

    def _selected_sale(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0 or not getattr(self, "_sales", None):
            return None
        return self._sales[row]

    def _reprint(self) -> None:
        sale = self._selected_sale()
        if sale is None:
            InfoBar.warning(title="Sin selección",
                            content="Seleccione un ticket de la lista.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        items = self.ctx.sales.get_sale_items(sale["id"])
        TicketPreviewDialog(self.ctx, sale, items, self.window()).exec()

    def validate(self) -> bool:
        self._reprint()
        return False  # el diálogo permanece abierto para reimprimir más tickets
