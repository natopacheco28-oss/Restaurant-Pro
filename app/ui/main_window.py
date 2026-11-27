"""Ventana principal de Restaurante Pro.

Ventana Fluent (qfluentwidgets.FluentWindow) con navegación lateral:
Caja · Catálogo · Inventario · Estadísticas · Ajustes.

Incluye:
- Atajo OCULTO Ctrl+P para cambiar la clave maestra (sin botón visible).
- Cierre seguro: bloquea el modo edición y crea el respaldo automático.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

from qfluentwidgets import FluentWindow, InfoBar, InfoBarPosition, NavigationItemPosition

from app.version import APP_NAME


class MainWindow(FluentWindow):
    """Ventana raíz con navegación lateral Fluent."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self._load_icon())
        self.setMinimumSize(1180, 760)
        self.resize(1440, 900)

        self._build_navigation()
        self._build_hidden_shortcuts()

    # ------------------------------------------------------------------

    def _load_icon(self):
        from PySide6.QtGui import QIcon

        from app.core.paths import icon_asset_path

        return QIcon(str(icon_asset_path()))

    def _build_navigation(self) -> None:
        """Registra los módulos en la navegación lateral."""
        from app.ui.modules.catalog_module import CatalogModule
        from app.ui.modules.inventory_module import InventoryModule
        from app.ui.modules.pos_module import PosModule
        from app.ui.modules.settings_module import SettingsModule
        from app.ui.modules.stats_module import StatsModule
        from app.ui.common import fi

        self.pos_module = PosModule(self.ctx)
        self.addSubInterface(
            self.pos_module, fi("SHOPPING_CART", "SELL", "HOME"), "Caja"
        )
        self.catalog_module = CatalogModule(self.ctx)
        self.addSubInterface(
            self.catalog_module, fi("TAG", "SHOP", "LIBRARY"), "Catálogo"
        )
        self.inventory_module = InventoryModule(self.ctx)
        self.addSubInterface(
            self.inventory_module, fi("BOX", "LIBRARY", "FOLDER_ADD"), "Inventario"
        )
        self.stats_module = StatsModule(self.ctx)
        self.addSubInterface(
            self.stats_module, fi("PIE_SINGLE", "IOT", "HISTORY"), "Estadísticas"
        )

        self.settings_module = SettingsModule(self.ctx)
        self.addSubInterface(
            self.settings_module,
            fi("SETTING"),
            "Ajustes",
            position=NavigationItemPosition.BOTTOM,
        )

    def _build_hidden_shortcuts(self) -> None:
        """Ctrl+P → cambio de clave maestra (menú oculto, sin botón visible)."""
        self._change_key_shortcut = QShortcut(QKeySequence("Ctrl+P"), self)
        self._change_key_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._change_key_shortcut.activated.connect(self._open_change_password)

    def _open_change_password(self) -> None:
        from app.ui.dialogs.security_dialogs import ChangePasswordDialog

        ChangePasswordDialog(self.ctx, self).exec()

    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt)
        """Cierre seguro: bloquear edición + respaldo automático."""
        # Bloqueo automático del modo edición al cerrar
        self.ctx.security.reset_session()

        # Respaldo automático con fecha y hora en el nombre (se conservan 10)
        try:
            backup = self.ctx.backup.backup_now("auto")
            InfoBar.success(
                title="Respaldo automático creado",
                content=backup.name,
                parent=self,
                position=InfoBarPosition.BOTTOM_RIGHT,
                duration=2500,
            )
        except Exception:
            # El cierre nunca debe impedirse por un fallo de respaldo
            pass

        QApplication.processEvents()
        super().closeEvent(event)
