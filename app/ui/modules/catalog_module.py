"""Módulo CATÁLOGO: productos y categorías con recetas.

- Panel izquierdo: categorías (alta/edición/baja).
- Panel derecho: productos con búsqueda, precio, disponibilidad y receta.
- Las ediciones requieren el modo edición (clave maestra una vez por sesión).
- Las tablas se actualizan al instante vía el bus de señales.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidgetItem,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    CardWidget,
    InfoBar,
    InfoBarPosition,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    StrongBodyLabel,
    TableWidget,
    TitleLabel,
    TransparentToolButton,
    ToolButton,
)

from app.printing.ticket_builder import money
from app.ui.common import (
    EditModeBanner,
    confirm,
    currency_of,
    fi,
)
from app.ui.dialogs.catalog_dialogs import CategoryDialog, ProductDialog


class CatalogModule(QWidget):
    """Página del catálogo."""

    def __init__(self, ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("CatalogModule")
        self._category_id: Optional[int] = None
        self._search_text = ""
        self._build_ui()
        self._reload_categories()
        self._reload_products()

        self.ctx.bus.categoriesChanged.connect(self._reload_categories)
        self.ctx.bus.productsChanged.connect(self._reload_products)
        self.ctx.bus.editModeChanged.connect(lambda _: self._update_buttons())

    # ==================================================================
    # UI
    # ==================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(TitleLabel("Catálogo"))
        header.addStretch(1)
        self._banner = EditModeBanner(self.ctx)
        header.addWidget(self._banner)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(16)

        # ---------------- Categorías ----------------
        categories_card = CardWidget()
        cats_layout = QVBoxLayout(categories_card)
        cats_layout.setContentsMargins(14, 14, 14, 14)
        cats_layout.setSpacing(8)

        cats_header = QHBoxLayout()
        cats_header.addWidget(StrongBodyLabel("Categorías"))
        cats_header.addStretch(1)
        self._cat_add = ToolButton(fi("ADD"))
        self._cat_add.setToolTip("Nueva categoría")
        self._cat_add.clicked.connect(self._add_category)
        self._cat_edit = ToolButton(fi("EDIT"))
        self._cat_edit.setToolTip("Renombrar categoría")
        self._cat_edit.clicked.connect(self._edit_category)
        self._cat_delete = TransparentToolButton(fi("DELETE"))
        self._cat_delete.setToolTip("Eliminar categoría")
        self._cat_delete.clicked.connect(self._delete_category)
        cats_header.addWidget(self._cat_add)
        cats_header.addWidget(self._cat_edit)
        cats_header.addWidget(self._cat_delete)
        cats_layout.addLayout(cats_header)

        self._categories_list = ListWidget()
        self._categories_list.setFrameShape(ListWidget.Shape.NoFrame)
        self._categories_list.currentRowChanged.connect(self._on_category_selected)
        cats_layout.addWidget(self._categories_list, 1)
        categories_card.setFixedWidth(260)
        body.addWidget(categories_card)

        # ---------------- Productos ----------------
        products_card = CardWidget()
        prod_layout = QVBoxLayout(products_card)
        prod_layout.setContentsMargins(14, 14, 14, 14)
        prod_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self._search = SearchLineEdit()
        self._search.setPlaceholderText("Buscar producto…")
        self._search.textChanged.connect(self._on_search)
        toolbar.addWidget(self._search, 1)

        self._add_button = PrimaryPushButton("Agregar producto")
        self._add_button.setIcon(fi("ADD"))
        self._add_button.clicked.connect(self._add_product)
        toolbar.addWidget(self._add_button)

        self._edit_button = PushButton("Editar")
        self._edit_button.setIcon(fi("EDIT"))
        self._edit_button.clicked.connect(self._edit_product)
        toolbar.addWidget(self._edit_button)

        self._toggle_button = PushButton("Desactivar")
        self._toggle_button.setIcon(fi("HIDE", "PAUSE", "CLOSE"))
        self._toggle_button.setToolTip("Activar o desactivar la venta del producto")
        self._toggle_button.clicked.connect(self._toggle_available)
        toolbar.addWidget(self._toggle_button)

        self._delete_button = ToolButton(fi("DELETE"))
        self._delete_button.setToolTip("Eliminar producto")
        self._delete_button.clicked.connect(self._delete_product)
        toolbar.addWidget(self._delete_button)
        prod_layout.addLayout(toolbar)

        self._table = TableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            ["Nombre", "Categoría", "Precio", "Receta", "Disponible"]
        )
        self._table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setWordWrap(False)
        self._table.setBorderVisible(True)
        self._table.setBorderRadius(8)
        self._table.doubleClicked.connect(lambda _: self._edit_product())
        prod_layout.addWidget(self._table, 1)
        body.addWidget(products_card, 1)

        root.addLayout(body, 1)

    # ==================================================================
    # Carga de datos
    # ==================================================================

    def _reload_categories(self) -> None:
        self._categories_list.clear()
        self._categories = self.ctx.catalog.list_categories()
        for cat in self._categories:
            label = f"{cat['name']}  ({cat['product_count']})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, cat["id"])
            self._categories_list.addItem(item)
        self._reload_category_chips()

    def _reload_category_chips(self) -> None:
        pass  # los chips viven en el módulo Caja; se recargan vía bus

    def _reload_products(self) -> None:
        products = self.ctx.catalog.list_products(
            search=self._search_text, category_id=self._category_id
        )
        self._table.setRowCount(len(products))
        currency = currency_of(self.ctx.settings)

        for row, product in enumerate(products):
            self._table.setItem(row, 0, QTableWidgetItem(product["name"]))
            self._table.setItem(
                row, 1, QTableWidgetItem(product["category_name"] or "—")
            )
            self._table.setItem(
                row, 2, QTableWidgetItem(money(product["price"], currency))
            )
            recipe = f"{product['recipe_count']} insumo(s)" if product["recipe_count"] else "—"
            self._table.setItem(row, 3, QTableWidgetItem(recipe))
            available = QTableWidgetItem("Sí" if product["available"] else "No")
            if not product["available"]:
                available.setForeground(Qt.GlobalColor.red)
            self._table.setItem(row, 4, available)

        self._update_buttons()

    def _on_search(self, text: str) -> None:
        self._search_text = text.strip()
        self._reload_products()

    def _on_category_selected(self, row: int) -> None:
        if 0 <= row < len(getattr(self, "_categories", [])):
            self._category_id = self._categories[row]["id"]
        else:
            self._category_id = None
        self._reload_products()

    def _selected_product(self) -> Optional[dict]:
        row = self._table.currentRow()
        if row < 0:
            return None
        # Se re-consulta por id almacenado en la fila
        products = self.ctx.catalog.list_products(
            search=self._search_text, category_id=self._category_id
        )
        if row < len(products):
            return products[row]
        return None

    # ==================================================================
    # Acciones de categorías
    # ==================================================================

    def _require_unlock(self) -> bool:
        """Verifica el modo edición; si está bloqueado abre el diálogo."""
        if self.ctx.security.is_unlocked:
            return True
        from app.ui.dialogs.security_dialogs import UnlockDialog

        UnlockDialog(self.ctx, self.window()).exec()
        return self.ctx.security.is_unlocked

    def _add_category(self) -> None:
        if not self._require_unlock():
            return
        CategoryDialog(self.ctx, self.window()).exec()

    def _edit_category(self) -> None:
        if not self._require_unlock():
            return
        row = self._categories_list.currentRow()
        if row < 0 or not getattr(self, "_categories", None):
            InfoBar.warning(title="Sin selección",
                            content="Seleccione una categoría.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        CategoryDialog(self.ctx, self.window(), self._categories[row]).exec()

    def _delete_category(self) -> None:
        if not self._require_unlock():
            return
        row = self._categories_list.currentRow()
        if row < 0 or not getattr(self, "_categories", None):
            return
        cat = self._categories[row]
        if confirm(
            self, "Eliminar categoría",
            f"¿Eliminar «{cat['name']}»? Sus {cat['product_count']} producto(s) "
            f"quedarán sin categoría.",
        ):
            self.ctx.catalog.delete_category(cat["id"])

    # ==================================================================
    # Acciones de productos
    # ==================================================================

    def _add_product(self) -> None:
        if not self._require_unlock():
            return
        ProductDialog(self.ctx, self.window(), default_category=self._category_id).exec()

    def _edit_product(self) -> None:
        if not self._require_unlock():
            return
        product = self._selected_product()
        if product is None:
            InfoBar.warning(title="Sin selección",
                            content="Seleccione un producto de la tabla.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        ProductDialog(self.ctx, self.window(), product).exec()

    def _toggle_available(self) -> None:
        if not self._require_unlock():
            return
        product = self._selected_product()
        if product is None:
            return
        self.ctx.catalog.set_product_available(
            product["id"], not product["available"]
        )

    def _delete_product(self) -> None:
        if not self._require_unlock():
            return
        product = self._selected_product()
        if product is None:
            return
        if confirm(self, "Eliminar producto",
                   f"¿Eliminar «{product['name']}»? Esta acción no se puede deshacer."):
            self.ctx.catalog.delete_product(product["id"])

    def _update_buttons(self) -> None:
        """Los botones de edición piden la clave al usarse (_require_unlock)."""
        pass
