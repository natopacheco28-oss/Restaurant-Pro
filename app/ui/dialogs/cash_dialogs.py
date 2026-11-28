"""Diálogos de caja: apertura con fondo inicial y corte de caja.

El corte muestra las ventas de la sesión agrupadas por método de pago,
el efectivo esperado (fondo + ventas en efectivo) y calcula la diferencia
con el conteo real.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QWidget,
)

from app.ui.components.spinboxes import AppDoubleSpinBox
from qfluentwidgets import (
    CaptionLabel,
    LineEdit,
    MessageBoxBase,
    StrongBodyLabel,
    SubtitleLabel,
)

from app.core.services.sales_service import PAYMENT_METHODS
from app.printing.ticket_builder import money
from app.ui.common import currency_of, format_dt


class OpenCashDialog(MessageBoxBase):
    """Apertura de caja con fondo inicial."""

    def __init__(self, ctx, parent: QWidget):
        super().__init__(parent)
        self.ctx = ctx

        self.viewLayout.addWidget(SubtitleLabel("Abrir caja"))
        caption = CaptionLabel(
            "Defina el fondo inicial (efectivo que queda en caja al comenzar "
            "el día). Puede ser 0."
        )
        caption.setWordWrap(True)
        self.viewLayout.addWidget(caption)

        grid = QGridLayout()
        grid.addWidget(QLabel("Fondo inicial:"), 0, 0)
        self._fund_edit = AppDoubleSpinBox()
        self._fund_edit.setRange(0.0, 999999.0)
        self._fund_edit.setDecimals(2)
        self._fund_edit.setSingleStep(100.0)
        self._fund_edit.setValue(0.0)
        grid.addWidget(self._fund_edit, 0, 1)
        self.viewLayout.addLayout(grid)

        self.yesButton.setText("Abrir caja")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(380)

    @property
    def fund(self) -> float:
        return self._fund_edit.value()


class CashCutDialog(MessageBoxBase):
    """Corte de caja: resumen de la sesión + conteo + diferencia."""

    def __init__(self, ctx, session: dict, parent: QWidget):
        super().__init__(parent)
        self.ctx = ctx
        self.session = session
        self.currency = currency_of(ctx.settings)

        totals = ctx.sales.session_totals(session["id"])
        cash_expected = round(
            session["initial_fund"] + totals["methods"].get("efectivo", {}).get("total", 0),
            2,
        )

        self.viewLayout.addWidget(SubtitleLabel("Corte de caja"))
        self.viewLayout.addWidget(CaptionLabel(
            f"Abierta el {format_dt(session['opened_at'])} · "
            f"Fondo inicial {money(session['initial_fund'], self.currency)}"
        ))

        # --- Ventas por método de pago ---
        table = QTableWidget(max(len(totals["methods"]), 1), 3)
        table.setHorizontalHeaderLabels(["Método", "Tickets", "Total"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.verticalHeader().setVisible(False)
        table.setFrameShape(QTableWidget.Shape.NoFrame)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(40 + 30 * max(len(totals["methods"]), 1))

        if totals["methods"]:
            for row, (method_key, data) in enumerate(totals["methods"].items()):
                table.setItem(row, 0, QTableWidgetItem(
                    PAYMENT_METHODS.get(method_key, method_key)))
                table.setItem(row, 1, QTableWidgetItem(str(data["count"])))
                table.setItem(row, 2, QTableWidgetItem(money(data["total"], self.currency)))
        else:
            table.setItem(0, 0, QTableWidgetItem("Sin ventas en esta sesión"))
        self.viewLayout.addWidget(table)

        summary = StrongBodyLabel(
            f"Ventas totales: {money(totals['grand_total'], self.currency)} · "
            f"{totals['grand_count']} ticket(s) · "
            f"Efectivo esperado: {money(cash_expected, self.currency)}"
        )
        summary.setWordWrap(True)
        self.viewLayout.addWidget(summary)

        # --- Conteo real ---
        grid = QGridLayout()
        grid.addWidget(QLabel("Efectivo contado:"), 0, 0)
        self._counted_edit = AppDoubleSpinBox()
        self._counted_edit.setRange(0.0, 999999.0)
        self._counted_edit.setDecimals(2)
        self._counted_edit.setValue(cash_expected)
        grid.addWidget(self._counted_edit, 0, 1)
        grid.addWidget(QLabel("Nota del corte:"), 1, 0)
        self._note_edit = LineEdit()
        self._note_edit.setPlaceholderText("Opcional")
        grid.addWidget(self._note_edit, 1, 1)
        self.viewLayout.addLayout(grid)

        self._difference_label = SubtitleLabel("")
        self.viewLayout.addWidget(self._difference_label)
        self._counted_edit.valueChanged.connect(self._update_difference)
        self._update_difference()

        self.yesButton.setText("Cerrar caja")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(460)

    def _update_difference(self) -> None:
        expected = float(self.session["initial_fund"]) + self.ctx.sales.session_totals(
            self.session["id"])["methods"].get("efectivo", {}).get("total", 0)
        difference = self._counted_edit.value() - expected
        color = "#22a06b" if abs(difference) < 0.01 else "#d13438"
        text = "Diferencia: $0.00 (cuadra ✓)" if abs(difference) < 0.01 else (
            f"Sobra: {money(difference, self.currency)}"
            if difference > 0
            else f"Falta: {money(-difference, self.currency)}"
        )
        self._difference_label.setText(text)
        self._difference_label.setStyleSheet(f"color: {color};")

    @property
    def counted(self) -> float:
        return self._counted_edit.value()

    @property
    def note(self) -> str:
        return self._note_edit.text().strip()
