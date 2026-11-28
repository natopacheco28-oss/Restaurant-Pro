"""Diálogo de cobro (checkout) de la caja.

Muestra el resumen del carrito y permite:
- Elegir método de pago: efectivo / tarjeta / transferencia.
- Descuento opcional (monto fijo o porcentaje).
- Propina opcional (precargada con el porcentaje sugerido de Ajustes).
- Pago en efectivo con cálculo de cambio en vivo.
- Nombre del mesero y del cliente (pedidos a domicilio).

Al validar devuelve un diccionario con todos los valores para `SalesService.checkout`.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.spinboxes import AppDoubleSpinBox
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    StrongBodyLabel,
    SubtitleLabel,
)

from app.core.services.sales_service import ORDER_TYPES, PAYMENT_METHODS
from app.printing.ticket_builder import money
from app.ui.common import currency_of


class CheckoutDialog(MessageBoxBase):
    """Cobro de la venta actual."""

    def __init__(self, ctx, cart: list[dict], order_type: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.cart = cart
        self.order_type = order_type
        self._computed: Optional[dict] = None

        currency = currency_of(ctx.settings)
        tip_suggested = float(ctx.settings.get("ticket.tip_suggested", 0) or 0)
        self._subtotal = round(
            sum(float(i["unit_price"]) * float(i["quantity"]) for i in cart), 2
        )

        # ---------------- Encabezado ----------------
        self.viewLayout.addWidget(SubtitleLabel("Cobrar venta"))
        header = CaptionLabel(
            f"Pedido: {ORDER_TYPES.get(order_type, order_type)} · "
            f"{len(cart)} producto(s)"
        )
        self.viewLayout.addWidget(header)

        # ---------------- Partidas ----------------
        self._table = QTableWidget(min(len(cart), 6), 3)
        self._table.setHorizontalHeaderLabels(["Producto", "Cant.", "Importe"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setFrameShape(QTableWidget.Shape.NoFrame)
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        for row, item in enumerate(self._table_row_data()):
            name = QTableWidgetItem(item["name"])
            if item.get("note"):
                name.setText(f"{item['name']} ({item['note']})")
            self._table.setItem(row, 0, name)
            self._table.setItem(row, 1, QTableWidgetItem(item["qty"]))
            self._table.setItem(row, 2, QTableWidgetItem(money(item["total"], currency)))
        self._table.setMinimumHeight(min(len(cart) * 28 + 36, 220))
        self.viewLayout.addWidget(self._table)

        # ---------------- Formulario de pago ----------------
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        grid.addWidget(QLabel("Método de pago:"), 0, 0)
        self._method_combo = ComboBox()
        for key, label in PAYMENT_METHODS.items():
            self._method_combo.addItem(label, userData=key)
        grid.addWidget(self._method_combo, 0, 1)

        grid.addWidget(QLabel("Mesero:"), 1, 0)
        self._waiter_edit = LineEdit()
        self._waiter_edit.setPlaceholderText("Opcional")
        grid.addWidget(self._waiter_edit, 1, 1)

        grid.addWidget(QLabel("Cliente:"), 2, 0)
        self._customer_edit = LineEdit()
        self._customer_edit.setPlaceholderText("Nombre para pedidos a domicilio")
        grid.addWidget(self._customer_edit, 2, 1)

        grid.addWidget(QLabel("Descuento:"), 3, 0)
        self._discount_edit = AppDoubleSpinBox()
        self._discount_edit.setRange(0.0, self._subtotal)
        self._discount_edit.setDecimals(2)
        self._discount_edit.setSingleStep(5.0)
        self._discount_edit.setValue(0.0)
        grid.addWidget(self._discount_edit, 3, 1)

        self._discount_type_combo = ComboBox()
        self._discount_type_combo.addItem("Monto fijo", userData="amount")
        self._discount_type_combo.addItem("Porcentaje %", userData="percent")
        grid.addWidget(self._discount_type_combo, 3, 2)

        grid.addWidget(QLabel("Propina:"), 4, 0)
        tip_box = QHBoxLayout()
        self._tip_check = CheckBox(f"Incluir (sugerido {tip_suggested:g}%)")
        self._tip_edit = AppDoubleSpinBox()
        self._tip_edit.setRange(0.0, 999999.0)
        self._tip_edit.setDecimals(2)
        self._tip_edit.setEnabled(False)
        tip_box.addWidget(self._tip_check)
        tip_box.addWidget(self._tip_edit, 1)
        grid.addLayout(tip_box, 4, 1, 1, 2)

        grid.addWidget(QLabel("Pago recibido:"), 5, 0)
        self._paid_edit = AppDoubleSpinBox()
        self._paid_edit.setRange(0.0, 999999.0)
        self._paid_edit.setDecimals(2)
        self._paid_edit.setSingleStep(50.0)
        grid.addWidget(self._paid_edit, 5, 1)

        self._print_check = CheckBox("Imprimir ticket al confirmar")
        self._print_check.setChecked(bool(ctx.settings.get("ticket.auto_print", True)))
        grid.addWidget(self._print_check, 6, 0, 1, 2)

        self.viewLayout.addLayout(grid)

        # ---------------- Totales ----------------
        totals_box = QVBoxLayout()
        totals_box.setSpacing(4)
        self._tip_suggested_value = round(self._subtotal * tip_suggested / 100.0, 2)
        self._totals_label = StrongBodyLabel("")
        self._change_label = SubtitleLabel("")
        totals_box.addWidget(self._totals_label)
        totals_box.addWidget(self._change_label)
        self.viewLayout.addLayout(totals_box)

        # Botones Fluent de MessageBoxBase
        self.yesButton.setText("Confirmar cobro")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(460)

        # ---------------- Señales ----------------
        self._method_combo.currentIndexChanged.connect(self._on_method_changed)
        self._discount_edit.valueChanged.connect(self._recalc)
        self._discount_type_combo.currentIndexChanged.connect(self._recalc)
        self._tip_check.toggled.connect(self._on_tip_toggled)
        self._tip_edit.valueChanged.connect(self._recalc)
        self._paid_edit.valueChanged.connect(self._recalc)

        if self.order_type == "domicilio":
            self._customer_edit.setFocus()
        self._on_method_changed()
        self._tip_edit.setValue(self._tip_suggested_value)
        self._recalc()

    # ------------------------------------------------------------------
    # Cálculo en vivo
    # ------------------------------------------------------------------

    def _table_row_data(self) -> list[dict]:
        rows = []
        for item in self.cart:
            qty = f"{float(item['quantity']):g}"
            total = round(float(item["unit_price"]) * float(item["quantity"]), 2)
            rows.append({"name": item["name"], "qty": qty, "total": total,
                         "note": (item.get("note") or "").strip()})
        return rows

    def _on_method_changed(self) -> None:
        is_cash = self._method_combo.currentData() == "efectivo"
        self._paid_edit.setEnabled(is_cash)
        self._change_label.setVisible(is_cash)
        self._recalc()

    def _on_tip_toggled(self, checked: bool) -> None:
        self._tip_edit.setEnabled(checked)
        self._recalc()

    def _recalc(self) -> None:
        currency = currency_of(self.ctx.settings)
        tax_rate = float(self.ctx.settings.get("ticket.tax_rate", 0) or 0)

        discount = self._discount_value()
        tip = self._tip_edit.value() if self._tip_check.isChecked() else 0.0
        taxable = round(self._subtotal - discount, 2)
        tax = round(taxable * tax_rate / 100.0, 2)
        total = round(taxable + tax + tip, 2)

        self._totals_label.setText(
            f"Subtotal {money(self._subtotal, currency)}   ·   "
            f"Descuento -{money(discount, currency)}   ·   "
            f"Impuesto {money(tax, currency)}   ·   "
            f"Propina {money(tip, currency)}   ·   "
            f"TOTAL {money(total, currency)}"
        )

        if self._method_combo.currentData() == "efectivo":
            paid = self._paid_edit.value()
            change = paid - total
            color = "#22a06b" if change >= 0 else "#d13438"
            self._change_label.setText(
                f"Cambio: {money(max(change, 0), currency)}"
                if change >= 0
                else f"Faltan: {money(-change, currency)}"
            )
            self._change_label.setStyleSheet(f"color: {color};")
            self.yesButton.setEnabled(True)
        else:
            self._paid_edit.setValue(total)

    def _discount_value(self) -> float:
        value = self._discount_edit.value()
        if self._discount_type_combo.currentData() == "percent":
            return round(min(self._subtotal * value / 100.0, self._subtotal), 2)
        return round(value, 2)

    # ------------------------------------------------------------------
    # Validación y resultado
    # ------------------------------------------------------------------

    def validate(self) -> bool:
        """Al pulsar «Confirmar cobro»: valida y prepara los datos de la venta."""
        tax_rate = float(self.ctx.settings.get("ticket.tax_rate", 0) or 0)

        discount = self._discount_value()
        tip = self._tip_edit.value() if self._tip_check.isChecked() else 0.0
        taxable = round(self._subtotal - discount, 2)
        tax = round(taxable * tax_rate / 100.0, 2)
        total = round(taxable + tax + tip, 2)

        if total <= 0:
            InfoBar.error(title="Cobro inválido",
                          content="El total debe ser mayor a 0.",
                          parent=self, position=InfoBarPosition.TOP, duration=3000)
            return False

        payment_method = self._method_combo.currentData()
        if payment_method == "efectivo" and self._paid_edit.value() + 1e-9 < total:
            InfoBar.error(title="Pago insuficiente",
                          content="El pago recibido es menor que el total.",
                          parent=self, position=InfoBarPosition.TOP, duration=3000)
            return False

        self._computed = {
            "order_type": self.order_type,
            "payment_method": payment_method,
            "discount": discount,
            "tip": tip,
            "paid": self._paid_edit.value() if payment_method == "efectivo" else total,
            "waiter": self._waiter_edit.text().strip(),
            "customer": self._customer_edit.text().strip(),
            "print": self._print_check.isChecked(),
            "subtotal": self._subtotal,
            "tax": tax,
            "total": total,
        }
        return True

    def computed(self) -> Optional[dict]:
        return self._computed
