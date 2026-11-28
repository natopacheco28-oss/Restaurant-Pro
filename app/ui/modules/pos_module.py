"""Módulo CAJA (punto de venta).

- Cuadrícula de productos por categoría con búsqueda rápida.
- Carrito con cantidades, notas por producto, descuento y propina opcional.
- Tipo de pedido: mesa / para llevar / a domicilio.
- Métodos de pago con cálculo de cambio.
- Apertura y cierre de caja (corte) con fondo inicial y diferencia.
- Ticket impreso al cobrar y reimpresión de tickets anteriores.
- El inventario se descuenta automáticamente vía las recetas ligadas.
"""
from __future__ import annotations

from typing import Optional


from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CaptionLabel,
    FlowLayout,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
    TransparentToolButton,
    ToolButton,
)

from app.core.services.sales_service import ORDER_TYPES
from app.core.services.validators import ValidationError
from app.printing.ticket_builder import build_ticket_text, money
from app.ui.common import (
    ProductCard,
    currency_of,
    fi,
    make_segmented,
    confirm,
)
from app.ui.dialogs.cash_dialogs import CashCutDialog, OpenCashDialog
from app.ui.dialogs.payment_dialog import CheckoutDialog
from app.ui.dialogs.ticket_dialogs import SalesHistoryDialog

# Notas rápidas para el menú contextual de cada producto del carrito
QUICK_NOTES = ["Sin cebolla", "Sin picante", "Bien cocido", "Término medio",
               "Sin gluten", "Extra queso", "Para compartir"]


class PosModule(QWidget):
    """Página de punto de venta."""

    def __init__(self, ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.order_type = str(ctx.settings.get("pos.default_order_type", "mesa"))
        self.cart: list[dict] = []
        self._category_id: Optional[int] = None
        self._search_text = ""
        self.setObjectName("PosModule")
        self._build_ui()
        self._reload_products()
        self._refresh_cash_status()

        # Actualización reactiva sin reiniciar
        self.ctx.bus.productsChanged.connect(self._reload_products)
        self.ctx.bus.categoriesChanged.connect(self._reload_products)
        self.ctx.bus.cashSessionChanged.connect(self._refresh_cash_status)

    # ==================================================================
    # Construcción de la UI
    # ==================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        # ---------------- Encabezado ----------------
        header = QHBoxLayout()
        title = TitleLabel("Caja")
        header.addWidget(title)
        header.addSpacing(8)
        self._cash_label = CaptionLabel("")
        header.addWidget(self._cash_label)
        header.addStretch(1)

        self._tickets_button = PushButton("Tickets")
        self._tickets_button.setIcon(fi("HISTORY", "DOCUMENT", "ZOOM"))
        self._tickets_button.clicked.connect(self._show_history)
        header.addWidget(self._tickets_button)

        self._cash_button = PrimaryPushButton("Abrir caja")
        self._cash_button.setIcon(fi("CASH", "MONEY", "WALLET"))
        self._cash_button.clicked.connect(self._cash_action)
        header.addWidget(self._cash_button)
        root.addLayout(header)

        # ---------------- Cuerpo: productos + carrito ----------------
        body = QHBoxLayout()
        body.setSpacing(16)

        # Panel izquierdo: búsqueda, categorías y cuadrícula
        left = QVBoxLayout()
        left.setSpacing(10)

        self._search = SearchLineEdit()
        self._search.setPlaceholderText("Buscar producto…")
        self._search.setFixedWidth(420)
        self._search.textChanged.connect(self._on_search)
        left.addWidget(self._search)

        self._categories_bar = make_segmented(
            [("all", "Todo")] + [
                (str(c["id"]), c["name"]) for c in self.ctx.catalog.list_categories()
            ],
            "all",
            self._on_category_change,
            parent=self,
        )
        left.addWidget(self._categories_bar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        if hasattr(self._scroll, "enableTransparentBackground"):
            self._scroll.enableTransparentBackground()
        self._grid_holder = QWidget()
        self._grid = FlowLayout(self._grid_holder, needAni=False)
        self._grid.setContentsMargins(0, 0, 8, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(12)
        self._scroll.setWidget(self._grid_holder)
        left.addWidget(self._scroll, 1)

        left_box = QWidget()
        left_box.setLayout(left)
        body.addWidget(left_box, 7)

        # Panel derecho: carrito
        self._cart_card = CartPanel(self.ctx, self)
        body.addWidget(self._cart_card, 3)
        root.addLayout(body, 1)

    # ==================================================================
    # Cuadrícula de productos
    # ==================================================================

    def _on_search(self, text: str) -> None:
        self._search_text = text.strip()
        self._reload_products()

    def _on_category_change(self, key) -> None:
        # La clave llega como str desde el segmented; si una señal Qt entregara
        # otro tipo (p. ej. bool) se trata como "Todo" en lugar de fallar.
        self._category_id = None if key == "all" or not str(key).isdigit() else int(key)
        self._reload_products()

    def _reload_products(self) -> None:
        """Recarga la cuadrícula según categoría y búsqueda activas."""
        # Limpiar cuadrícula. OJO: el FlowLayout de qfluentwidgets devuelve
        # el WIDGET directamente en takeAt (no un QLayoutItem) — llamar
        # .widget() sobre él reventaba con «'BodyLabel' object has no
        # attribute 'widget'» al pulsar «Todo»/categoría/buscar.
        from PySide6.QtWidgets import QWidget

        while self._grid.count():
            taken = self._grid.takeAt(0)
            widget = taken if isinstance(taken, QWidget) else taken.widget()
            if widget:
                widget.deleteLater()

        # Refrescar chips de categoría (por si se crearon categorías nuevas)
        products = self.ctx.catalog.list_products(
            search=self._search_text,
            category_id=self._category_id,
            only_available=True,
        )
        if not products:
            empty = BodyLabel(
                "No hay productos en esta categoría.\nAgregue productos en el "
                "módulo Catálogo (requiere desbloquear la edición)."
            )
            empty.setWordWrap(True)
            self._grid.addWidget(empty)
            return

        for product in products:
            card = ProductCard(product, self.ctx.settings)
            card.clicked.connect(self._add_to_cart)
            self._grid.addWidget(card)

    # ==================================================================
    # Carrito
    # ==================================================================

    def _add_to_cart(self, product: dict) -> None:
        """Agrega un producto (o suma cantidad si ya está sin nota)."""
        for item in self.cart:
            if item["product_id"] == product["id"] and not item["note"]:
                item["quantity"] += 1
                self._cart_card.refresh(self.cart)
                return
        self.cart.append({
            "product_id": product["id"],
            "name": product["name"],
            "unit_price": float(product["price"]),
            "quantity": 1,
            "note": "",
        })
        self._cart_card.refresh(self.cart)

    def add_free_item(self, item: dict) -> None:
        """Agrega una COMANDA libre (platillo fuera de catálogo) al carrito."""
        self.cart.append({
            "product_id": None,
            "name": str(item["name"]).strip(),
            "unit_price": float(item["unit_price"]),
            "quantity": float(item["quantity"]),
            "note": str(item.get("note") or ""),
        })
        self._cart_card.refresh(self.cart)

    def _clear_cart(self) -> None:
        self.cart.clear()
        self._cart_card.refresh(self.cart)

    # ==================================================================
    # Caja (apertura / corte)
    # ==================================================================

    def _refresh_cash_status(self) -> None:
        session = self.ctx.sales.current_session()
        currency = currency_of(self.ctx.settings)
        if session:
            opened = str(session["opened_at"])[11:16]
            self._cash_label.setText(
                f"• Caja abierta desde las {opened} — fondo "
                f"{money(session['initial_fund'], currency)}"
            )
            self._cash_button.setText("Corte de caja")
        else:
            self._cash_label.setText("• Caja cerrada — abra la caja para vender")
            self._cash_button.setText("Abrir caja")

    def _cash_action(self) -> None:
        session = self.ctx.sales.current_session()
        if session is None:
            dialog = OpenCashDialog(self.ctx, self.window())
            if dialog.exec():
                try:
                    self.ctx.sales.open_session(dialog.fund)
                    InfoBar.success(
                        title="Caja abierta",
                        content=f"Fondo inicial: {money(dialog.fund, currency_of(self.ctx.settings))}",
                        parent=self, position=InfoBarPosition.TOP, duration=3000,
                    )
                except ValidationError as exc:
                    InfoBar.error(title="No se pudo abrir la caja", content=str(exc),
                                  parent=self, position=InfoBarPosition.TOP, duration=4000)
            return

        dialog = CashCutDialog(self.ctx, session, self.window())
        if dialog.exec():
            try:
                summary = self.ctx.sales.close_session(
                    session["id"], dialog.counted, note=dialog.note
                )
                diff = summary["difference"]
                InfoBar.success(
                    title="Corte de caja realizado",
                    content=(
                        f"Efectivo esperado {money(summary['cash_expected'], currency_of(self.ctx.settings))} · "
                        f"Diferencia {money(diff, currency_of(self.ctx.settings))}"
                    ),
                    parent=self, position=InfoBarPosition.TOP, duration=6000,
                )
            except ValidationError as exc:
                InfoBar.error(title="No se pudo cerrar la caja", content=str(exc),
                              parent=self, position=InfoBarPosition.TOP, duration=4000)

    def _checkout(self) -> None:
        if not self.cart:
            InfoBar.warning(title="Carrito vacío",
                            content="Agregue productos para cobrar.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        if self.ctx.sales.current_session() is None:
            self._cash_action()
            if self.ctx.sales.current_session() is None:
                return

        dialog = CheckoutDialog(self.ctx, list(self.cart), self.order_type,
                                self.window())
        if not dialog.exec() or not dialog.computed():
            return
        data = dialog.computed()

        try:
            result = self.ctx.sales.checkout(
                items=list(self.cart),
                order_type=data["order_type"],
                payment_method=data["payment_method"],
                discount=data["discount"],
                tip=data["tip"],
                paid=data["paid"],
                waiter=data["waiter"],
                customer=data["customer"],
            )
        except ValidationError as exc:
            InfoBar.error(title="No se pudo cobrar", content=str(exc),
                          parent=self, position=InfoBarPosition.TOP, duration=5000)
            return

        sale = result["sale"]
        currency = currency_of(self.ctx.settings)

        # Alerta de insumos en stock bajo tras la venta
        if result["low_stock"]:
            InfoBar.warning(
                title="Inventario en stock mínimo",
                content="Reponer: " + ", ".join(sorted(set(result["low_stock"]))),
                parent=self, position=InfoBarPosition.TOP, duration=8000,
            )

        # Impresión del ticket
        if data["print"]:
            self._print_sale(result)

        InfoBar.success(
            title=f"Cobrado — Folio #{sale['folio']:06d}",
            content=(
                f"Total {money(sale['total'], currency)} · "
                f"Cambio {money(sale['change'], currency)}"
                if sale["payment_method"] == "efectivo"
                else f"Total {money(sale['total'], currency)}"
            ),
            parent=self, position=InfoBarPosition.TOP, duration=5000,
        )
        self._clear_cart()

    def _print_sale(self, result: dict) -> None:
        """Imprime el ticket de la venta recién cobrada."""
        sale, items = result["sale"], result["items"]
        text = build_ticket_text(sale, items, self.ctx.settings)
        logo_path = self._logo_path()
        ok, message = self.ctx.printer.print_sale_ticket(text, logo_path)
        if not ok:
            InfoBar.error(title="Error al imprimir el ticket", content=message,
                          parent=self, position=InfoBarPosition.TOP, duration=6000)

    def _logo_path(self) -> Optional[str]:
        """Ruta del logo para ESC/POS (personalizado o de assets)."""
        from app.core.paths import logo_asset_path, resolve_portable

        custom = self.ctx.settings.get("restaurant.logo_path", "")
        candidate = resolve_portable(custom) if custom else logo_asset_path()
        return str(candidate) if candidate.exists() else None

    def _show_history(self) -> None:
        SalesHistoryDialog(self.ctx, self.window()).exec()


class CartPanel(CardWidget):
    """Panel derecho: carrito, tipo de pedido, totales y botón de cobro."""

    def __init__(self, ctx, pos: PosModule):
        super().__init__(pos)
        self.ctx = ctx
        self.pos = pos
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        heading = StrongBodyLabel("Ticket actual")
        header.addWidget(heading)
        header.addStretch(1)
        # Comanda libre: platillo fuera del catálogo (p. ej. especial del día)
        comanda_button = PushButton("Agregar comanda")
        comanda_button.setIcon(fi("ADD", "PLUS", "ADD_TO"))
        comanda_button.setToolTip("Agregar una comanda libre: platillo con "
                                  "nombre, cantidad, precio y nota propios")
        comanda_button.clicked.connect(self._add_comanda)
        header.addWidget(comanda_button)
        clear_button = TransparentToolButton(fi("DELETE", "CLOSE"))
        clear_button.setToolTip("Vaciar carrito")
        clear_button.clicked.connect(self._clear)
        header.addWidget(clear_button)
        layout.addLayout(header)

        # Tipo de pedido: mesa / llevar / domicilio
        self._order_bar = make_segmented(
            list(ORDER_TYPES.items()),
            self.pos.order_type,
            self._on_order_type,
            parent=self,
        )
        layout.addWidget(self._order_bar)

        # Lista del carrito
        self._list = QListWidget()
        self._list.setAlternatingRowColors(False)
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.setStyleSheet("QListWidget { background: transparent; }")
        layout.addWidget(self._list, 1)

        # Totales
        self._totals = CaptionLabel("Sin productos")
        self._totals.setWordWrap(True)
        layout.addWidget(self._totals)

        checkout_button = PrimaryPushButton("Cobrar")
        checkout_button.setIcon(fi("CASH", "MONEY", "ACCEPT"))
        checkout_button.setFixedHeight(40)
        checkout_button.clicked.connect(self.pos._checkout)
        layout.addWidget(checkout_button)

    def _add_comanda(self) -> None:
        """Comanda libre: captura nombre/cantidad/precio/nota y la agrega."""
        dialog = ComandaDialog(self.ctx, self.window())
        if not dialog.exec():
            return
        self.pos.add_free_item(dialog.result_item())

    def _on_order_type(self, key) -> None:
        # Clave inválida (p. ej. un bool de una señal Qt) → tipo por defecto.
        self.pos.order_type = key if key in ORDER_TYPES else next(iter(ORDER_TYPES))

    def _clear(self) -> None:
        if not self.pos.cart:
            return
        if confirm(self, "Vaciar carrito", "¿Eliminar todos los productos del carrito?"):
            self.pos._clear_cart()

    def refresh(self, cart: list[dict]) -> None:
        """Redibuja el carrito y los totales."""
        self._list.clear()
        currency = currency_of(self.ctx.settings)

        for item in cart:
            widget = CartRow(item, self.ctx, self)
            row_item = QListWidgetItem(self._list)
            row_item.setSizeHint(widget.sizeHint())
            self._list.addItem(row_item)
            self._list.setItemWidget(row_item, widget)

        if cart:
            subtotal = round(sum(i["unit_price"] * i["quantity"] for i in cart), 2)
            count = len(cart)
            self._totals.setText(
                f"{count} producto(s) · Subtotal {money(subtotal, currency)} · "
                f"Descuento, propina e impuesto se aplican al cobrar"
            )
        else:
            self._totals.setText("Sin productos — toque un producto de la cuadrícula")


class CartRow(QWidget):
    """Fila del carrito: nombre, cantidad, nota y eliminar."""

    def __init__(self, item: dict, ctx, panel: CartPanel):
        super().__init__()
        self.item = item
        self.ctx = ctx
        self.panel = panel

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        text_box = QVBoxLayout()
        text_box.setSpacing(0)
        name = StrongBodyLabel(f"{item['quantity']:g} × {item['name']}")
        text_box.addWidget(name)
        detail = CaptionLabel(
            money(item["unit_price"], currency_of(ctx.settings))
            + (f" · «{item['note']}»" if item["note"] else "")
        )
        text_box.addWidget(detail)
        layout.addLayout(text_box, 1)

        minus = ToolButton(fi("CARE_LEFT_SOLID", "REMOVE", "CLOSE"))
        minus.setToolTip("Quitar uno")
        minus.clicked.connect(lambda: self._change_quantity(-1))
        plus = ToolButton(fi("CARE_RIGHT_SOLID", "ADD"))
        plus.setToolTip("Agregar uno")
        plus.clicked.connect(lambda: self._change_quantity(+1))
        note_button = TransparentToolButton(fi("EDIT", "PEN", "INFO"))
        note_button.setToolTip("Nota del producto (ej. sin cebolla)")
        note_button.clicked.connect(self._edit_note)
        layout.addWidget(minus)
        layout.addWidget(plus)
        layout.addWidget(note_button)

    # ------------------------------------------------------------------

    def _change_quantity(self, delta: int) -> None:
        self.item["quantity"] += delta
        if self.item["quantity"] <= 0:
            self.panel.pos.cart.remove(self.item)
        self.panel.refresh(self.panel.pos.cart)

    def _edit_note(self) -> None:
        """Nota libre + sugerencias rápidas (ej. «sin cebolla»)."""
        dialog = NoteDialog(self.ctx, self.item, self.window())
        dialog.exec()
        self.panel.refresh(self.panel.pos.cart)


class ComandaDialog(MessageBoxBase):
    """Captura de una COMANDA libre (platillo fuera del catálogo).

    Nombre, cantidad, precio y nota — se agrega al ticket como renglón
    sin producto asociado; el checkout ya admite partidas sin receta.
    """

    def __init__(self, ctx, parent: QWidget):
        super().__init__(parent)
        self.ctx = ctx
        from app.ui.components import make_double_spin

        self.viewLayout.addWidget(SubtitleLabel("Agregar comanda"))

        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText(
            "Platillo o bebida — ej. Especial del día")
        self.viewLayout.addWidget(BodyLabel("Nombre:"))
        self.viewLayout.addWidget(self._name_edit)

        row = QHBoxLayout()
        self._qty_edit = make_double_spin(0.1, 9999.0, 1.0, decimals=3,
                                          minimum_width=110)
        self._price_edit = make_double_spin(0.0, 999999.0, 0.0, decimals=2,
                                            minimum_width=130)
        row.addWidget(BodyLabel("Cantidad:"))
        row.addWidget(self._qty_edit)
        row.addSpacing(16)
        row.addWidget(BodyLabel("Precio unitario:"))
        row.addWidget(self._price_edit, 1)
        self.viewLayout.addLayout(row)

        self._note_edit = LineEdit()
        self._note_edit.setPlaceholderText(
            "Nota para cocina (opcional) — ej. sin cebolla, para llevar")
        self.viewLayout.addWidget(BodyLabel("Nota:"))
        self.viewLayout.addWidget(self._note_edit)

        self.widget.setMinimumWidth(480)

    def result_item(self) -> dict:
        return {
            "name": self._name_edit.text().strip(),
            "unit_price": round(float(self._price_edit.value()), 2),
            "quantity": float(self._qty_edit.value()),
            "note": self._note_edit.text().strip(),
        }

    def validate(self) -> bool:
        name = self._name_edit.text().strip()
        if not name:
            self._name_edit.setFocus()
            InfoBar.warning(title="Falta el nombre",
                            content="Escribe el nombre de la comanda.",
                            parent=self, position=InfoBarPosition.TOP,
                            duration=2500)
            return False
        if self._price_edit.value() <= 0:
            self._price_edit.setFocus()
            InfoBar.warning(title="Precio inválido",
                            content="El precio unitario debe ser mayor a 0.",
                            parent=self, position=InfoBarPosition.TOP,
                            duration=2500)
            return False
        if self._qty_edit.value() <= 0:
            self._qty_edit.setFocus()
            InfoBar.warning(title="Cantidad inválida",
                            content="La cantidad debe ser mayor a 0.",
                            parent=self, position=InfoBarPosition.TOP,
                            duration=2500)
            return False
        return True


class NoteDialog(MessageBoxBase):
    """Captura de nota por producto con botones rápidos."""

    def __init__(self, ctx, item: dict, parent: QWidget):
        super().__init__(parent)
        self.item = item

        self.viewLayout.addWidget(SubtitleLabel(f"Nota · {item['name']}"))
        self._edit = LineEdit()
        self._edit.setPlaceholderText("Ej. sin cebolla, bien cocido…")
        self._edit.setText(item["note"] or "")
        self.viewLayout.addWidget(self._edit)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)
        for note in QUICK_NOTES[:4]:
            button = PushButton(note)
            button.clicked.connect(
                lambda _=False, n=note: self._edit.setText(
                    (self._edit.text() + ", " + n).strip(", ")
                )
            )
            quick_row.addWidget(button)
        self.viewLayout.addLayout(quick_row)

        clear_button = PushButton("Quitar nota")
        clear_button.clicked.connect(self._clear_note)
        self.viewLayout.addWidget(clear_button)

        self.yesButton.setText("Guardar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(420)

    def _clear_note(self) -> None:
        self._edit.clear()

    def validate(self) -> bool:
        self.item["note"] = self._edit.text().strip()
        return True
