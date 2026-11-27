"""Módulo INVENTARIO (almacén) — 5 vistas con navegación segmentada.

1. INSUMOS     — tabla con insignias de estado (normal/bajo/agotado), stock
                 ideal, proveedor y acciones (alta, edición, entradas/salidas).
2. KARDEX      — historial completo e inmutable, filtrable por insumo, tipo,
                 rango de fechas y motivo, con exportación a Excel/CSV.
3. POR CADUCAR — lotes con semáforo (vencido rojo, próximo naranja, vigente
                 verde) y acciones rápidas: dar salida / marcar merma.
4. SIN MOVIMIENTO — stock estancado con días, valor inmovilizado y sugerencia.
5. COMPRAS     — lista de compras sugerida editable, agrupada por proveedor,
                 con costo estimado, exportación (Excel/CSV/PDF/ticket) y
                 conversión de la lista en entradas con un clic.

Las acciones que modifican datos requieren el modo edición (clave maestra
una vez por sesión); la consulta y exportación son libres.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    StrongBodyLabel,
    TableWidget,
    TitleLabel,
    TransparentToolButton,
)

from app.core.export import rows_to_csv, rows_to_excel, rows_to_pdf
from app.core.services.inventory_service import MOVEMENT_TYPES
from app.printing.ticket_builder import money
from app.ui.common import (
    COLOR_ERROR,
    COLOR_OK,
    COLOR_WARN,
    EditModeBanner,
    currency_of,
    fi,
    make_segmented,
    state_color,
)
from app.ui.dialogs.inventory_dialogs import MovementDialog


def _tinted_item(text: str, color: str) -> QTableWidgetItem:
    """Celda con texto de color para insignias de estado."""
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    return item


class InventoryModule(QWidget):
    """Página del almacén."""

    TABS = [
        ("insumos", "Insumos"),
        ("kardex", "Kardex"),
        ("caducidad", "Por caducar"),
        ("estancados", "Sin movimiento"),
        ("compras", "Compras"),
    ]

    def __init__(self, ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("InventoryModule")
        self._search_text = ""
        self._build_ui()
        self.refresh_all()

        # Actualización reactiva sin reiniciar
        self.ctx.bus.ingredientsChanged.connect(self._page_insumos.reload)
        self.ctx.bus.movementsChanged.connect(self._page_kardex.reload)
        self.ctx.bus.movementsChanged.connect(self._page_caducidad.reload)
        self.ctx.bus.movementsChanged.connect(self._page_estancados.reload)
        self.ctx.bus.shoppingListChanged.connect(self._page_compras.reload_lists)
        self.ctx.bus.settingsChanged.connect(self.refresh_all)

    # ==================================================================
    # Construcción de la UI
    # ==================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(TitleLabel("Inventario"))
        header.addStretch(1)
        self._banner = EditModeBanner(self.ctx)
        header.addWidget(self._banner)
        root.addLayout(header)

        self._tabs = make_segmented(self.TABS, "insumos", self._switch, parent=self)
        root.addWidget(self._tabs)

        self._stack = QStackedWidget()
        self._page_insumos = IngredientsPage(self.ctx, self)
        self._page_kardex = KardexPage(self.ctx, self)
        self._page_caducidad = ExpiryPage(self.ctx, self)
        self._page_estancados = StalePage(self.ctx, self)
        self._page_compras = ShoppingPage(self.ctx, self)
        for page in (self._page_insumos, self._page_kardex, self._page_caducidad,
                     self._page_estancados, self._page_compras):
            self._stack.addWidget(page)
        root.addWidget(self._stack, 1)

    def _switch(self, key) -> None:
        # Señales Qt pueden entregar un valor inesperado (p. ej. un bool):
        # si la clave no es válida se regresa a la primera pestaña.
        keys = [k for k, _ in self.TABS]
        if key not in keys:
            key = keys[0]
        self._stack.setCurrentIndex(keys.index(key))
        page = self._stack.currentWidget()
        if hasattr(page, "reload"):
            page.reload()

    def refresh_all(self) -> None:
        """Recarga todas las vistas (señales, cambio de ajustes, tema)."""
        self._page_insumos.reload()
        self._page_kardex.reload()
        self._page_caducidad.reload()
        self._page_estancados.reload()
        self._page_compras.reload_lists()

    # ------------------------------------------------------------------
    # Utilidades compartidas por las páginas
    # ------------------------------------------------------------------

    def require_unlock(self) -> bool:
        """Modo edición (clave maestra una vez por sesión) para modificar."""
        if self.ctx.security.is_unlocked:
            return True
        from app.ui.dialogs.security_dialogs import UnlockDialog

        UnlockDialog(self.ctx, self.window()).exec()
        return self.ctx.security.is_unlocked

    def focus_ingredient(self, ingredient_id: int) -> None:
        """Va a la pestaña Insumos y selecciona el insumo (desde alertas)."""
        self._tabs.setCurrentItem("insumos")
        self._stack.setCurrentIndex(0)
        self._page_insumos.select_ingredient(ingredient_id)

    def focus_expiry(self) -> None:
        self._tabs.setCurrentItem("caducidad")
        self._stack.setCurrentIndex(2)
        self._page_caducidad.reload()


# ======================================================================
# 1. INSUMOS
# ======================================================================

class IngredientsPage(CardWidget):
    """Tabla de insumos con insignias de estado y acciones del almacén."""

    def __init__(self, ctx, module: InventoryModule):
        super().__init__(module)
        self.ctx = ctx
        self.module = module
        self._ingredients: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self._low_banner = CaptionLabel("")
        self._low_banner.setStyleSheet(f"color: {COLOR_ERROR}; font-weight: 600;")
        self._low_banner.setVisible(False)
        layout.addWidget(self._low_banner)

        toolbar = QHBoxLayout()
        self._search = SearchLineEdit()
        self._search.setPlaceholderText("Buscar insumo o proveedor…")
        self._search.textChanged.connect(self.reload)
        toolbar.addWidget(self._search, 1)

        self._add_button = PrimaryPushButton("Agregar insumo")
        self._add_button.setIcon(fi("ADD"))
        self._add_button.clicked.connect(self._add_ingredient)
        toolbar.addWidget(self._add_button)

        self._edit_button = PushButton("Editar")
        self._edit_button.setIcon(fi("EDIT"))
        self._edit_button.clicked.connect(self._edit_ingredient)
        toolbar.addWidget(self._edit_button)

        self._in_button = PushButton("Entrada")
        self._in_button.setIcon(fi("DOWNLOAD", "ADD"))
        self._in_button.setToolTip("Registrar entrada (crea lote)")
        self._in_button.clicked.connect(lambda: self._movement("entrada"))
        toolbar.addWidget(self._in_button)

        self._out_button = PushButton("Salida")
        self._out_button.setIcon(fi("UPLOAD", "REMOVE"))
        self._out_button.setToolTip("Salida por PEPS/FEFO")
        self._out_button.clicked.connect(lambda: self._movement("salida"))
        toolbar.addWidget(self._out_button)

        self._waste_button = PushButton("Merma")
        self._waste_button.setIcon(fi("DELETE", "CLOSE"))
        self._waste_button.clicked.connect(lambda: self._movement("merma"))
        toolbar.addWidget(self._waste_button)

        self._adjust_button = PushButton("Ajuste")
        self._adjust_button.setIcon(fi("SYNC", "UPDATE"))
        self._adjust_button.clicked.connect(lambda: self._movement("ajuste"))
        toolbar.addWidget(self._adjust_button)

        self._delete_button = TransparentToolButton(fi("DELETE"))
        self._delete_button.setToolTip("Eliminar insumo")
        self._delete_button.clicked.connect(self._delete_ingredient)
        toolbar.addWidget(self._delete_button)
        layout.addLayout(toolbar)

        self._table = TableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels(
            ["Insumo", "Unidad", "Stock", "Mínimo", "Ideal", "Costo",
             "Proveedor", "Estado"]
        )
        self._configure_table(self._table)
        layout.addWidget(self._table, 1)

    def reload(self) -> None:
        self._ingredients = self.ctx.inventory.list_ingredients(self._search.text().strip())
        table = self._table
        table.setRowCount(len(self._ingredients))
        currency = currency_of(self.ctx.settings)

        low_names = []
        for row, ing in enumerate(self._ingredients):
            estado = ing["estado"]
            if estado in ("bajo", "agotado") and ing["min_stock"] > 0:
                low_names.append(f"{ing['name']} ({ing['stock']:g}/{ing['min_stock']:g})")

            values = [
                ing["name"], ing["unit"], f"{ing['stock']:g}",
                f"{ing['min_stock']:g}", f"{ing['ideal_stock']:g}",
                money(ing["cost"], currency), ing["supplier"] or "—", "",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (2, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                if estado == "agotado":
                    item.setBackground(QColor(255, 82, 82, 46))
                elif estado == "bajo":
                    item.setBackground(QColor(230, 162, 60, 40))
                table.setItem(row, col, item)
            table.setItem(row, 7, _tinted_item(
                {"normal": "Normal", "bajo": "Bajo", "agotado": "Agotado"}[estado],
                state_color(estado)))

        if low_names:
            self._low_banner.setText("⚠ Stock bajo: " + ", ".join(low_names[:8])
                                     + ("…" if len(low_names) > 8 else ""))
            self._low_banner.setVisible(True)
        else:
            self._low_banner.setVisible(False)

    def _configure_table(self, table: TableWidget) -> None:
        table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(False)
        table.setBorderVisible(True)
        table.setBorderRadius(8)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)

    def _selected(self) -> Optional[dict]:
        row = self._table.currentRow()
        if 0 <= row < len(self._ingredients):
            return self._ingredients[row]
        return None

    def select_ingredient(self, ingredient_id: int) -> None:
        """Selecciona un insumo por id (llega desde el centro de alertas)."""
        self.reload()
        for row, ing in enumerate(self._ingredients):
            if ing["id"] == ingredient_id:
                self._table.selectRow(row)
                break

    # -- acciones -------------------------------------------------------

    def _add_ingredient(self) -> None:
        if not self.module.require_unlock():
            return
        from app.ui.dialogs.inventory_dialogs import IngredientDialog

        IngredientDialog(self.ctx, self.window()).exec()

    def _edit_ingredient(self) -> None:
        if not self.module.require_unlock():
            return
        ing = self._selected()
        if ing is None:
            InfoBar.warning(title="Sin selección",
                            content="Seleccione un insumo de la tabla.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        from app.ui.dialogs.inventory_dialogs import IngredientDialog

        IngredientDialog(self.ctx, self.window(), ing).exec()

    def _movement(self, movement_type: str) -> None:
        if not self.module.require_unlock():
            return
        ing = self._selected()
        if ing is None:
            InfoBar.warning(title="Sin selección",
                            content="Seleccione el insumo para el movimiento.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        MovementDialog(self.ctx, ing, movement_type, self.window()).exec()

    def _delete_ingredient(self) -> None:
        if not self.module.require_unlock():
            return
        ing = self._selected()
        if ing is None:
            return
        from app.ui.common import confirm

        if confirm(self, "Eliminar insumo",
                   f"¿Eliminar «{ing['name']}»? Los productos que lo usan en su "
                   f"receta dejarán de descontarlo."):
            self.ctx.inventory.delete_ingredient(ing["id"])


# ======================================================================
# 2. KARDEX
# ======================================================================

class KardexPage(CardWidget):
    """Historial de movimientos filtrable y exportable (inmutable)."""

    HEADERS = ["Fecha", "Insumo", "Tipo", "Cantidad", "Lote", "Costo unit.",
               "Proveedor", "Motivo", "Usuario", "Stock resultante"]

    def __init__(self, ctx, module: InventoryModule):
        super().__init__(module)
        self.ctx = ctx
        self.module = module

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # --- Filtros ---
        filters = QHBoxLayout()
        filters.addWidget(CaptionLabel("Insumo:"))
        self._ingredient_combo = ComboBox()
        self._ingredient_combo.setMinimumWidth(150)
        filters.addWidget(self._ingredient_combo)

        filters.addWidget(CaptionLabel("Tipo:"))
        self._type_combo = ComboBox()
        self._type_combo.addItem("Todos", userData=None)
        for key, label in MOVEMENT_TYPES.items():
            self._type_combo.addItem(label, userData=key)
        filters.addWidget(self._type_combo)

        filters.addWidget(CaptionLabel("Desde:"))
        self._from_picker = self._date_picker()
        filters.addWidget(self._from_picker)
        filters.addWidget(CaptionLabel("Hasta:"))
        self._to_picker = self._date_picker()
        filters.addWidget(self._to_picker)

        filters.addWidget(CaptionLabel("Motivo:"))
        self._reason_edit = SearchLineEdit()
        self._reason_edit.setPlaceholderText("Buscar motivo o nota…")
        self._reason_edit.setFixedWidth(180)
        self._reason_edit.returnPressed.connect(self.reload)
        filters.addWidget(self._reason_edit)

        apply_button = PushButton("Aplicar")
        apply_button.setIcon(fi("FILTER", "SEARCH", "ZOOM"))
        apply_button.clicked.connect(self.reload)
        filters.addWidget(apply_button)
        layout.addLayout(filters)

        actions = QHBoxLayout()
        self._count_label = CaptionLabel("")
        actions.addWidget(self._count_label)
        actions.addStretch(1)
        excel_button = PushButton("Exportar Excel")
        excel_button.setIcon(fi("SAVE_AS", "SAVE"))
        excel_button.clicked.connect(lambda: self._export("excel"))
        actions.addWidget(excel_button)
        csv_button = PushButton("Exportar CSV")
        csv_button.setIcon(fi("DOCUMENT", "SAVE"))
        csv_button.clicked.connect(lambda: self._export("csv"))
        actions.addWidget(csv_button)
        layout.addLayout(actions)

        # --- Tabla ---
        self._table = TableWidget()
        self._table.setColumnCount(len(self.HEADERS))
        self._table.setHorizontalHeaderLabels(self.HEADERS)
        self._table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setWordWrap(False)
        self._table.setBorderVisible(True)
        self._table.setBorderRadius(8)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, 1)

        note = CaptionLabel(
            "El kardex es inmutable: los movimientos no se editan ni se "
            "borran; las correcciones se hacen con un AJUSTE.")
        layout.addWidget(note)

        self.reload()

    @staticmethod
    def _date_picker():
        from app.ui.dialogs.inventory_dialogs import _make_date_picker

        return _make_date_picker()

    def reload(self) -> None:
        # Catálogo de insumos del filtro (se refresca con cada recarga)
        current = self._ingredient_combo.currentData() if \
            self._ingredient_combo.count() else None
        self._ingredient_combo.blockSignals(True)
        self._ingredient_combo.clear()
        self._ingredient_combo.addItem("Todos", userData=None)
        for ing in self.ctx.inventory.list_ingredients():
            self._ingredient_combo.addItem(ing["name"], userData=ing["id"])
        if current is not None:
            index = self._ingredient_combo.findData(current)
            self._ingredient_combo.setCurrentIndex(max(index, 0))
        self._ingredient_combo.blockSignals(False)

        from app.ui.dialogs.inventory_dialogs import picker_date

        movements = self.ctx.inventory.list_movements(
            limit=400,
            ingredient_id=self._ingredient_combo.currentData(),
            mtype=self._type_combo.currentData(),
            since=(picker_date(self._from_picker).isoformat()
                   if picker_date(self._from_picker) else None),
            until=(picker_date(self._to_picker).isoformat()
                   if picker_date(self._to_picker) else None),
            reason_search=self._reason_edit.text().strip(),
        )
        self._rows = movements

        table = self._table
        table.setRowCount(len(movements))
        type_labels = MOVEMENT_TYPES
        color_by_type = {
            "entrada": COLOR_OK, "salida": COLOR_WARN,
            "merma": COLOR_ERROR, "venta": COLOR_OK, "ajuste": COLOR_WARN,
        }
        for row, mov in enumerate(movements):
            reason = mov["reason"] or mov["note"] or ""
            values = [
                str(mov["datetime"]), mov["ingredient_name"],
                type_labels.get(mov["type"], mov["type"]),
                f"{mov['quantity']:+g} {mov['unit']}",
                mov["lot_number"] or "—",
                (money(mov["unit_cost"], currency_of(self.ctx.settings))
                 if mov["unit_cost"] is not None else "—"),
                mov["supplier"] or "—", reason or "—",
                mov["user"] or "—", f"{mov['stock_after']:g}",
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(value))
            table.setItem(row, 2, _tinted_item(
                type_labels.get(mov["type"], mov["type"]),
                color_by_type.get(mov["type"], COLOR_WARN)))
            table.setItem(row, 3, _tinted_item(
                f"{mov['quantity']:+g} {mov['unit']}",
                color_by_type.get(mov["type"], COLOR_WARN)))

        self._count_label.setText(f"{len(movements)} movimiento(s) mostrados")

    def _export(self, kind: str) -> None:
        rows = getattr(self, "_rows", [])
        if not rows:
            InfoBar.warning(title="Nada que exportar",
                            content="Ajuste los filtros para tener movimientos.",
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar kardex",
            f"RestaurantePro_kardex.{('xlsx' if kind == 'excel' else 'csv')}",
            "Excel (*.xlsx)" if kind == "excel" else "CSV (*.csv)")
        if not path:
            return
        headers = self.HEADERS
        out = []
        for mov in rows:
            out.append([
                str(mov["datetime"]), mov["ingredient_name"],
                MOVEMENT_TYPES.get(mov["type"], mov["type"]),
                mov["quantity"], mov["lot_number"] or "",
                mov["unit_cost"] if mov["unit_cost"] is not None else "",
                mov["supplier"] or "", mov["reason"] or mov["note"] or "",
                mov["user"] or "", mov["stock_after"],
            ])
        try:
            if kind == "excel":
                rows_to_excel(path, "Kardex", headers, out)
            else:
                rows_to_csv(path, headers, out)
        except Exception as exc:
            InfoBar.error(title="No se pudo exportar", content=str(exc),
                          parent=self, position=InfoBarPosition.TOP, duration=5000)
            return
        InfoBar.success(title="Kardex exportado", content=str(path),
                        parent=self, position=InfoBarPosition.TOP, duration=4000)


# ======================================================================
# 3. POR CADUCAR
# ======================================================================

class ExpiryPage(CardWidget):
    """Lotes con semáforo de caducidad y acciones rápidas."""

    STATE_LABELS = {"vencido": "Vencido", "por_caducar": "Por caducar",
                    "vigente": "Vigente", "sin_caducidad": "Sin caducidad"}

    def __init__(self, ctx, module: InventoryModule):
        super().__init__(module)
        self.ctx = ctx
        self.module = module
        self._lots: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        actions = QHBoxLayout()
        self._summary = CaptionLabel("")
        actions.addWidget(self._summary)
        actions.addStretch(1)
        out_button = PrimaryPushButton("Dar salida del lote")
        out_button.setIcon(fi("UPLOAD", "REMOVE"))
        out_button.clicked.connect(lambda: self._quick_action("salida"))
        actions.addWidget(out_button)
        waste_button = PushButton("Marcar como merma")
        waste_button.setIcon(fi("DELETE", "CLOSE"))
        waste_button.clicked.connect(lambda: self._quick_action("merma"))
        actions.addWidget(waste_button)
        layout.addLayout(actions)

        self._table = TableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["Insumo", "Lote", "Caduca", "Días", "Cantidad", "Valor", "Estado"]
        )
        self._table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setWordWrap(False)
        self._table.setBorderVisible(True)
        self._table.setBorderRadius(8)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._table.doubleClicked.connect(lambda _: self._quick_action("salida"))
        layout.addWidget(self._table, 1)

        self.reload()

    def reload(self) -> None:
        self._lots = self.ctx.inventory.list_lots(only_active=True)
        table = self._table
        table.setRowCount(len(self._lots))

        counts = {"vencido": 0, "por_caducar": 0}
        for row, lot in enumerate(self._lots):
            estado = lot["estado"]
            if estado in counts:
                counts[estado] += 1
            days = lot["days_left"]
            values = [
                lot["ingredient_name"], lot["lot_number"] or "—",
                lot["expiration_date"] or "—",
                ("—" if days is None else str(days)),
                f"{lot['quantity']:g} {lot['unit']}",
                money(lot["value"], currency_of(self.ctx.settings)), "",
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(value))
            table.setItem(row, 6, _tinted_item(
                self.STATE_LABELS.get(estado, estado), state_color(estado)))
            # Tinte de fondo por urgencia
            if estado == "vencido":
                color = QColor(255, 82, 82, 46)
            elif estado == "por_caducar":
                color = QColor(230, 162, 60, 40)
            else:
                color = QColor(34, 160, 107, 26)
            for col in range(6):
                item = table.item(row, col)
                if item:
                    item.setBackground(color)

        self._summary.setText(
            f"{counts['vencido']} lote(s) vencido(s) · "
            f"{counts['por_caducar']} por caducar — ordenados por urgencia"
        )

    def _selected(self) -> Optional[dict]:
        row = self._table.currentRow()
        if 0 <= row < len(self._lots):
            return self._lots[row]
        return None

    def _quick_action(self, movement_type: str) -> None:
        """Salida o merma del lote seleccionado (descuenta ESE lote)."""
        if not self.module.require_unlock():
            return
        lot = self._selected()
        if lot is None:
            InfoBar.warning(title="Sin selección",
                            content="Seleccione un lote de la tabla.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        ingredient = self.ctx.inventory.get_ingredient(lot["ingredient_id"])
        if ingredient is None:
            return
        MovementDialog(
            self.ctx, ingredient, movement_type, self.window(),
            default_quantity=max(float(lot["quantity"]), 0.001),
            force_lot_id=lot["id"],
        ).exec()


# ======================================================================
# 4. SIN MOVIMIENTO (stock estancado)
# ======================================================================

class StalePage(CardWidget):
    """Insumos con existencia sin salidas en X días."""

    def __init__(self, ctx, module: InventoryModule):
        super().__init__(module)
        self.ctx = ctx
        self.module = module
        self._rows: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        actions = QHBoxLayout()
        self._summary = CaptionLabel("")
        actions.addWidget(self._summary)
        actions.addStretch(1)
        out_button = PrimaryPushButton("Dar salida")
        out_button.setIcon(fi("UPLOAD", "REMOVE"))
        out_button.clicked.connect(self._give_out)
        actions.addWidget(out_button)
        layout.addLayout(actions)

        self._table = TableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["Insumo", "Cantidad", "Costo unit.", "Valor inmovilizado",
             "Días sin salida", "Última salida", "Sugerencia"]
        )
        self._table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setWordWrap(False)
        self._table.setBorderVisible(True)
        self._table.setBorderRadius(8)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, 1)

        self.reload()

    def reload(self) -> None:
        self._rows = self.ctx.inventory.stale_ingredients()
        table = self._table
        table.setRowCount(len(self._rows))
        currency = currency_of(self.ctx.settings)
        total_value = round(sum(row["value"] for row in self._rows), 2)
        stale_days = int(self.ctx.settings.get("inventory.stale_days", 30) or 30)

        suggestion = ("Úselo en promoción, menú del día o platillo especial; "
                      "si ya no es útil, regístrale merma.")
        for row_index, row in enumerate(self._rows):
            values = [
                row["name"], f"{row['stock']:g} {row['unit']}",
                money(row["cost"], currency), money(row["value"], currency),
                str(int(row["days_stale"])), row["last_out"] or "nunca",
                suggestion,
            ]
            for col, value in enumerate(values):
                table.setItem(row_index, col, QTableWidgetItem(value))
            table.setItem(row_index, 4, _tinted_item(
                str(int(row["days_stale"])), COLOR_WARN))

        self._summary.setText(
            f"{len(self._rows)} insumo(s) sin salidas en {stale_days} días · "
            f"valor inmovilizado: {money(total_value, currency)}"
        )

    def _selected(self) -> Optional[dict]:
        row = self._table.currentRow()
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _give_out(self) -> None:
        if not self.module.require_unlock():
            return
        row = self._selected()
        if row is None:
            InfoBar.warning(title="Sin selección",
                            content="Seleccione un insumo de la tabla.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        ingredient = self.ctx.inventory.get_ingredient(row["id"])
        if ingredient is not None:
            MovementDialog(self.ctx, ingredient, "salida", self.window()).exec()


# ======================================================================
# 5. COMPRAS (lista sugerida)
# ======================================================================

class ShoppingPage(CardWidget):
    """Lista de compras: sugerida, editable, exportable y convertible."""

    def __init__(self, ctx, module: InventoryModule):
        super().__init__(module)
        self.ctx = ctx
        self.module = module
        self._list_id: Optional[int] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # --- Barra de listas ---
        lists_row = QHBoxLayout()
        lists_row.addWidget(CaptionLabel("Lista:"))
        self._list_combo = ComboBox()
        self._list_combo.setMinimumWidth(240)
        self._list_combo.currentIndexChanged.connect(self._on_list_changed)
        lists_row.addWidget(self._list_combo, 1)

        generate_button = PrimaryPushButton("Generar sugerida")
        generate_button.setIcon(fi("SHOP", "SHOPPING_CART", "ADD"))
        generate_button.setToolTip(
            "Crea una lista con los insumos en stock bajo o agotados")
        generate_button.clicked.connect(self._generate)
        lists_row.addWidget(generate_button)

        self._status_label = StrongBodyLabel("")
        lists_row.addWidget(self._status_label)
        layout.addLayout(lists_row)

        # --- Acciones ---
        actions = QHBoxLayout()
        add_button = PushButton("Agregar renglón")
        add_button.setIcon(fi("ADD"))
        add_button.clicked.connect(self._add_item)
        actions.addWidget(add_button)

        remove_button = PushButton("Quitar seleccionado")
        remove_button.setIcon(fi("DELETE", "CLOSE"))
        remove_button.clicked.connect(self._remove_item)
        actions.addWidget(remove_button)

        save_button = PushButton("Guardar cambios")
        save_button.setIcon(fi("SAVE", "ACCEPT"))
        save_button.clicked.connect(self._save_changes)
        actions.addWidget(save_button)

        self._buy_button = PrimaryPushButton("Registrar compra")
        self._buy_button.setIcon(fi("DOWNLOAD", "ACCEPT", "CARE_RIGHT_SOLID"))
        self._buy_button.setToolTip(
            "Convierte los renglones en ENTRADAS de inventario con un clic")
        self._buy_button.clicked.connect(self._convert)
        actions.addWidget(self._buy_button)
        actions.addStretch(1)

        export_button = PushButton("Excel")
        export_button.setIcon(fi("SAVE_AS", "SAVE"))
        export_button.clicked.connect(lambda: self._export("excel"))
        actions.addWidget(export_button)
        csv_button = PushButton("CSV")
        csv_button.setIcon(fi("DOCUMENT", "SAVE"))
        csv_button.clicked.connect(lambda: self._export("csv"))
        actions.addWidget(csv_button)
        pdf_button = PushButton("PDF")
        pdf_button.setIcon(fi("PDF", "DOCUMENT", "SAVE"))
        pdf_button.clicked.connect(lambda: self._export("pdf"))
        actions.addWidget(pdf_button)
        print_button = PushButton("Imprimir (ticket)")
        print_button.setIcon(fi("PRINT", "SHARE", "DOCUMENT"))
        print_button.clicked.connect(self._print_list)
        actions.addWidget(print_button)
        layout.addLayout(actions)

        # --- Tabla de renglones ---
        self._table = TableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["✓", "Insumo", "Cantidad", "Unidad", "Costo est.", "Proveedor"]
        )
        self._table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setWordWrap(False)
        self._table.setBorderVisible(True)
        self._table.setBorderRadius(8)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table, 1)

        self._total_label = StrongBodyLabel("")
        layout.addWidget(self._total_label)

        self.reload_lists()

    # ------------------------------------------------------------------

    def reload_lists(self) -> None:
        """Recarga el combo de listas guardadas y la lista seleccionada."""
        lists = self.ctx.shopping.list_lists()
        self._lists = lists
        self._list_combo.blockSignals(True)
        self._list_combo.clear()
        for header in lists:
            estado = "✔ comprada" if header["status"] == "comprada" else "pendiente"
            self._list_combo.addItem(
                f"#{header['id']} · {str(header['datetime'])[:16]} · "
                f"{header['item_count']} renglón(es) · {estado}",
                userData=header["id"],
            )
        self._list_combo.blockSignals(False)

        if self._list_id is not None:
            index = self._list_combo.findData(self._list_id)
            if index >= 0:
                self._list_combo.setCurrentIndex(index)
            else:
                self._list_id = None  # la lista se eliminó
        if self._list_id is None and lists:
            self._select_list(lists[0]["id"])
        elif self._list_id is None:
            self._show_items(None)
        else:
            self._select_list(self._list_id)

    def _select_list(self, list_id: int) -> None:
        self._list_id = list_id
        self._show_items(self.ctx.shopping.get_list(list_id))

    def _on_list_changed(self, index: int) -> None:
        if 0 <= index < len(getattr(self, "_lists", [])):
            self._select_list(self._lists[index]["id"])

    def _show_items(self, header: Optional[dict]) -> None:
        """Dibuja los renglones (tabla editable: cantidad y casilla ✓)."""
        self._loading = True  # evitar loops de itemChanged
        table = self._table
        table.setRowCount(0)
        if header is None:
            self._status_label.setText("")
            self._total_label.setText(
                "Sin listas — pulse «Generar sugerida» para crear una con los "
                "insumos en stock bajo o agotados.")
            self._loading = False
            return

        items = header["items"]
        table.setRowCount(len(items))
        currency = currency_of(self.ctx.settings)
        for row, item in enumerate(items):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                           | Qt.ItemFlag.ItemIsEnabled
                           | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Checked if item["checked"]
                                else Qt.CheckState.Unchecked)
            table.setItem(row, 0, check)

            table.setItem(row, 1, QTableWidgetItem(
                item["name"] + ("" if item["ingredient_id"] else "  (libre)")))
            qty_item = QTableWidgetItem(f"{item['quantity']:g}")
            qty_item.setFlags(qty_item.flags() | Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 2, qty_item)
            table.setItem(row, 3, QTableWidgetItem(item["unit"]))
            table.setItem(row, 4, QTableWidgetItem(
                money(item["estimated_cost"], currency)))
            table.setItem(row, 5, QTableWidgetItem(item["supplier"] or "—"))

        status = "✔ comprada" if header["status"] == "comprada" else "pendiente"
        self._status_label.setText(f"Estado: {status}")
        total = self.ctx.shopping.total_cost(items)
        groups = self.ctx.shopping.group_by_supplier(items)
        suppliers = ", ".join(groups.keys())
        self._total_label.setText(
            f"{len(items)} renglón(es) · Costo estimado total: "
            f"{money(total, currency)} · Proveedores: {suppliers or '—'}")
        self._loading = False

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------

    def _generate(self) -> None:
        """Crea una lista nueva con los insumos en stock bajo / agotados."""
        items = self.ctx.shopping.suggested_items()
        if not items:
            InfoBar.success(title="Nada que comprar",
                            content="Ningún insumo está en stock bajo o agotado.",
                            parent=self, position=InfoBarPosition.TOP, duration=3500)
            return
        list_id = self.ctx.shopping.create_list(items, note="Sugerida automáticamente")
        self._list_id = list_id
        self.reload_lists()
        InfoBar.success(title="Lista sugerida creada",
                        content=f"{len(items)} renglón(es) — revise cantidades y "
                                f"marque lo que no necesite.",
                        parent=self, position=InfoBarPosition.TOP, duration=4000)

    def _add_item(self) -> None:
        if self._list_id is None:
            InfoBar.warning(title="Sin lista",
                            content="Genere o cree una lista primero.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        from app.ui.dialogs.shopping_dialogs import ShoppingItemDialog

        dialog = ShoppingItemDialog(self.ctx, self.window())
        if dialog.exec():
            try:
                self.ctx.shopping.add_item(self._list_id, dialog.result_item())
                self._select_list(self._list_id)
            except Exception as exc:
                InfoBar.error(title="Renglón inválido", content=str(exc),
                              parent=self, position=InfoBarPosition.TOP,
                              duration=4000)

    def _remove_item(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        self.ctx.shopping.remove_item(item["id"])
        self._select_list(self._list_id)

    def _selected_item(self) -> Optional[dict]:
        row = self._table.currentRow()
        header = self.ctx.shopping.get_list(self._list_id) if self._list_id else None
        if header and 0 <= row < len(header["items"]):
            return header["items"][row]
        return None

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Casilla ✓ o cantidad editada en la tabla → guardar en la lista."""
        if getattr(self, "_loading", False) or self._list_id is None:
            return
        header = self.ctx.shopping.get_list(self._list_id)
        if header is None:
            return
        row, column = item.row(), item.column()
        if row >= len(header["items"]):
            return
        db_item = header["items"][row]
        try:
            if column == 0:
                self.ctx.shopping.update_item(
                    db_item["id"],
                    checked=(item.checkState() == Qt.CheckState.Checked))
            elif column == 2:
                quantity = float(item.text().replace(",", ".")) if item.text() else 0
                if quantity < 0:
                    raise ValueError
                self.ctx.shopping.update_item(db_item["id"], quantity=quantity)
            else:
                return  # otras columnas se cambian con «Agregar/Editar»
        except (ValueError, TypeError):
            InfoBar.error(title="Cantidad inválida",
                          content="Escriba un número mayor o igual a 0.",
                          parent=self, position=InfoBarPosition.TOP, duration=3000)
            self._select_list(self._list_id)
            return
        self._select_list(self._list_id)

    def _save_changes(self) -> None:
        """Aplica casillas y cantidades de la tabla a la lista guardada."""
        if self._list_id is None:
            return
        header = self.ctx.shopping.get_list(self._list_id)
        if header is None:
            return
        self._loading = True
        for row, db_item in enumerate(header["items"]):
            check = self._table.item(row, 0)
            qty = self._table.item(row, 2)
            checked = check is not None and check.checkState() == Qt.CheckState.Checked
            try:
                quantity = (float(qty.text().replace(",", ".")) if qty and qty.text()
                            else db_item["quantity"])
            except (ValueError, TypeError):
                quantity = db_item["quantity"]
            self.ctx.shopping.update_item(
                db_item["id"], quantity=quantity, checked=checked)
        self._loading = False
        self._select_list(self._list_id)
        InfoBar.success(title="Lista guardada", content=f"Lista #{self._list_id}",
                        parent=self, position=InfoBarPosition.TOP, duration=2500)

    def _convert(self) -> None:
        """Convierte la lista en entradas de inventario (requiere modo edición)."""
        if not self.module.require_unlock():
            return
        if self._list_id is None:
            return
        header = self.ctx.shopping.get_list(self._list_id)
        if header is None:
            return
        if header["status"] == "comprada":
            InfoBar.warning(title="Lista ya comprada",
                            content="Esta lista ya fue registrada como compra.",
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
            return

        from app.ui.common import confirm

        if not confirm(self, "Registrar compra",
                       f"¿Convertir la lista #{self._list_id} en entradas de "
                       f"inventario? Cada renglón creará una entrada con lote "
                       f"nuevo y la lista quedará como comprada."):
            return
        try:
            result = self.ctx.shopping.convert_to_entries(
                self._list_id, user=self._user())
        except Exception as exc:
            InfoBar.error(title="No se pudo registrar la compra", content=str(exc),
                          parent=self, position=InfoBarPosition.TOP, duration=5000)
            return
        self.reload_lists()
        InfoBar.success(
            title="Compra registrada",
            content=(f"{result['created']} entrada(s) creada(s)"
                     + (f" · {result['skipped']} renglón(es) libre(s) omitidos"
                        if result["skipped"] else "")),
            parent=self, position=InfoBarPosition.TOP, duration=5000)

    @staticmethod
    def _user() -> str:
        try:
            import getpass

            return getpass.getuser()
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Exportación / impresión
    # ------------------------------------------------------------------

    def _export_data(self) -> tuple[Optional[str], list[str], list[list]]:
        header = self.ctx.shopping.get_list(self._list_id) if self._list_id else None
        if header is None or not header["items"]:
            return None, [], []
        currency = currency_of(self.ctx.settings)
        rows = []
        for item in header["items"]:
            rows.append([
                "X" if item["checked"] else "", item["name"],
                item["quantity"], item["unit"],
                money(item["estimated_cost"], currency),
                item["supplier"] or "",
            ])
        title = f"Lista de compras #{header['id']}"
        return title, ["✓", "Insumo", "Cantidad", "Unidad", "Costo est.", "Proveedor"], rows

    def _export(self, kind: str) -> None:
        title, headers, rows = self._export_data()
        if title is None:
            InfoBar.warning(title="Nada que exportar",
                            content="No hay una lista con renglones.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        from PySide6.QtWidgets import QFileDialog

        extension = {"excel": "xlsx", "csv": "csv", "pdf": "pdf"}[kind]
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar lista de compras",
            f"RestaurantePro_compras_{title.split('#')[-1]}.{extension}",
            {"excel": "Excel (*.xlsx)", "csv": "CSV (*.csv)",
             "pdf": "PDF (*.pdf)"}[kind])
        if not path:
            return
        try:
            if kind == "excel":
                rows_to_excel(path, "Compras", headers, rows)
            elif kind == "csv":
                rows_to_csv(path, headers, rows)
            else:
                rows_to_pdf(path, title, headers, rows)
        except Exception as exc:
            InfoBar.error(title="No se pudo exportar", content=str(exc),
                          parent=self, position=InfoBarPosition.TOP, duration=5000)
            return
        InfoBar.success(title="Lista exportada", content=str(path),
                        parent=self, position=InfoBarPosition.TOP, duration=3500)

    def _print_list(self) -> None:
        """Imprime la lista por la impresora de tickets (58/80 mm)."""
        header = self.ctx.shopping.get_list(self._list_id) if self._list_id else None
        if header is None or not header["items"]:
            InfoBar.warning(title="Nada que imprimir",
                            content="No hay una lista con renglones.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        from app.printing.ticket_builder import build_ticket_text

        class _SettingsProxy:
            """Usa el nombre del restaurante con el rótulo de la lista."""

            def __init__(self, base, overrides):
                self._base = base
                self._overrides = overrides

            def get(self, key, default=None):
                return self._overrides.get(
                    key, self._base.get(key, default))

        total = self.ctx.shopping.total_cost(header["items"])
        proxy = _SettingsProxy(self.ctx.settings, {
            "restaurant.name": f"{self.ctx.settings.get('restaurant.name', '')} "
                               f"— LISTA DE COMPRAS #{header['id']}",
            "restaurant.slogan": "",
            "ticket.tax_rate": 0,
        })

        # Se aprovecha el builder del ticket: los renglones van como partidas
        sale = {
            "folio": header["id"], "datetime": str(header["datetime"])[:19],
            "order_type": "mesa", "payment_method": "efectivo",
            "subtotal": total, "discount": 0, "tax": 0, "tip": 0,
            "total": total, "paid": 0, "change": 0, "waiter": "", "customer": "",
        }
        items = [{"product_name": ("*" if it["checked"] else " ") + " " + it["name"],
                  "unit_price": it["estimated_cost"],
                  "quantity": it["quantity"], "note": it["supplier"] or ""}
                 for it in header["items"]]
        text = build_ticket_text(sale, items, proxy)
        ok, message = self.ctx.printer.print_sale_ticket(text, None)
        if ok:
            InfoBar.success(title="Lista enviada a imprimir", content=message,
                            parent=self, position=InfoBarPosition.TOP, duration=3500)
        else:
            InfoBar.error(title="Error de impresión", content=message,
                          parent=self, position=InfoBarPosition.TOP, duration=5000)
