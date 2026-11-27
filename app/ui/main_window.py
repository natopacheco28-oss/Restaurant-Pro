"""Ventana principal de Restaurante Pro.

Ventana Fluent (qfluentwidgets.FluentWindow) con navegación lateral:
Caja · Catálogo · Inventario · Estadísticas · Ajustes.

Incluye:
- Atajo OCULTO Ctrl+P para cambiar la clave maestra (sin botón visible).
- Centro de notificaciones del almacén: icono de campana con contador en la
  barra superior, revisión periódica (QTimer configurable en Ajustes),
  resumen al abrir el programa, alertas con InfoBar y notificación de la
  bandeja de Windows si el programa está minimizado (opcional).
- Cierre seguro: bloquea el modo edición y crea el respaldo automático.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from qfluentwidgets import (
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    TransparentToolButton,
)

from app.ui.common import COLOR_ERROR, fi
from app.version import APP_NAME

# Frecuencia de parpadeo del icono de campana cuando hay alertas nuevas
DEFAULT_ALERT_INTERVAL_MIN = 30


class BellButton(QWidget):
    """Botón de campana para la barra de título con insignia de contador."""

    def __init__(self, on_click, parent: QWidget | None = None):
        super().__init__(parent)
        self._count = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        self._button = TransparentToolButton(fi("BELL", "INFO", "MAIL"))
        self._button.setToolTip("Notificaciones del almacén")
        self._button.setFixedSize(34, 34)
        self._button.clicked.connect(on_click)
        layout.addWidget(self._button)

        # Insignia (contador de alertas) anclada a la esquina del botón
        self._badge = QLabel(self._button)
        self._badge.setFixedSize(18, 18)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setStyleSheet(
            f"background-color: {COLOR_ERROR}; color: white;"
            f"border-radius: 9px; font-size: 11px; font-weight: bold;")
        self._move_badge()

    def _move_badge(self) -> None:
        self._badge.move(self._button.width() - 14, 0)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt)
        self._move_badge()
        super().resizeEvent(event)

    def set_count(self, count: int) -> None:
        self._count = int(count)
        self._badge.setVisible(self._count > 0)
        self._badge.setText("99+" if self._count > 99 else str(self._count))
        self._button.setToolTip(
            f"Notificaciones del almacén ({self._count})"
            if self._count else "Notificaciones del almacén — sin alertas")


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
        self._build_title_bar_extras()
        self._build_hidden_shortcuts()
        self._build_alerts_system()

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

    def _build_title_bar_extras(self) -> None:
        """Campana del centro de notificaciones en la barra de título."""
        self._bell = BellButton(self._open_notifications)
        try:
            self.titleBar.layout().addWidget(self._bell, 0, Qt.AlignmentFlag.AlignRight)
        except Exception:
            # Barra de título no estándar: el botón no se muestra
            self._bell.hide()

    def _build_hidden_shortcuts(self) -> None:
        """Ctrl+P → cambio de clave maestra (menú oculto, sin botón visible)."""
        self._change_key_shortcut = QShortcut(QKeySequence("Ctrl+P"), self)
        self._change_key_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._change_key_shortcut.activated.connect(self._open_change_password)

    def _open_change_password(self) -> None:
        from app.ui.dialogs.security_dialogs import ChangePasswordDialog

        ChangePasswordDialog(self.ctx, self).exec()

    # ==================================================================
    # Sistema de notificaciones del almacén
    # ==================================================================

    def _build_alerts_system(self) -> None:
        """Revisión periódica de alertas + resumen al abrir el programa."""
        self._tray = None  # QSystemTrayIcon perezoso (solo si se necesita)

        self._alert_timer = QTimer(self)
        self._alert_timer.timeout.connect(self._check_alerts)
        self._apply_alert_interval()

        # Los cambios de Ajustes reprograman el temporizador
        self.ctx.bus.settingsChanged.connect(self._apply_alert_interval)

        # Resumen automático al abrir el programa
        QTimer.singleShot(1500, self._startup_summary)

    def _apply_alert_interval(self) -> None:
        try:
            minutes = int(self.ctx.settings.get(
                "inventory.alert_interval_min", DEFAULT_ALERT_INTERVAL_MIN) or 30)
        except (TypeError, ValueError):
            minutes = DEFAULT_ALERT_INTERVAL_MIN
        self._alert_timer.start(max(minutes, 1) * 60 * 1000)

    def _alert_interval_ms(self) -> int:
        try:
            minutes = int(self.ctx.settings.get(
                "inventory.alert_interval_min", DEFAULT_ALERT_INTERVAL_MIN) or 30)
        except (TypeError, ValueError):
            minutes = DEFAULT_ALERT_INTERVAL_MIN
        return max(minutes, 1) * 60 * 1000

    def _collect_alerts(self) -> list[dict]:
        alerts = self.ctx.alerts.collect()
        self._bell.set_count(len(alerts))
        return alerts

    def _check_alerts(self) -> None:
        """Revisión periódica: campana + InfoBar + bandeja si está minimizado."""
        alerts = self._collect_alerts()
        if not alerts:
            return
        first = alerts[0]
        InfoBar.warning(
            title=f"{len(alerts)} alerta(s) de almacén",
            content=(f"{first['title']}: {first['content']} — use la campana "
                     f"para ver todas."),
            parent=self, position=InfoBarPosition.BOTTOM_RIGHT, duration=8000,
        )
        # Notificación del sistema de Windows si está minimizado (opcional)
        if (self.isMinimized()
                and bool(self.ctx.settings.get(
                    "inventory.system_notifications", False))):
            self._notify_system(
                "Restaurante Pro — alertas de almacén",
                self.ctx.alerts.summary(alerts))

    def _startup_summary(self) -> None:
        """Resumen automático al abrir: «Hoy: 3 por caducar, 5 en stock bajo»."""
        alerts = self._collect_alerts()
        if not alerts:
            return
        InfoBar.info(
            title="Almacén",
            content=self.ctx.alerts.summary(alerts)
            + " — campana para revisar.",
            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=9000,
        )
        if bool(self.ctx.settings.get("inventory.system_notifications", False)) \
                and self.isMinimized():
            self._notify_system("Restaurante Pro",
                                self.ctx.alerts.summary(alerts))

    def _open_notifications(self) -> None:
        """Abre el centro de notificaciones (campana de la barra superior)."""
        from app.ui.dialogs.notifications_dialog import NotificationsDialog

        dialog = NotificationsDialog(
            self.ctx, self,
            on_focus=self._focus_inventory_ingredient,
        )
        dialog.exec()
        if dialog.changed:
            self._collect_alerts()

    def _focus_inventory_ingredient(self, ingredient_id: int) -> None:
        """Va al insumo en el módulo Inventario (desde una alerta)."""
        self.switchTo(self.inventory_module)
        self.inventory_module.focus_ingredient(ingredient_id)

    def _notify_system(self, title: str, message: str) -> None:
        """Notificación de la bandeja de Windows (solo si está minimizado)."""
        try:
            if self._tray is None:
                from PySide6.QtWidgets import QSystemTrayIcon

                self._tray = QSystemTrayIcon(self._load_icon(), self)
                self._tray.setToolTip(APP_NAME)
                self._tray.show()
            if self._tray is not None:
                from PySide6.QtWidgets import QSystemTrayIcon

                self._tray.showMessage(title, message,
                                       QSystemTrayIcon.MessageIcon.Information,
                                       6000)
        except Exception:
            # La notificación del sistema nunca debe romper la app
            pass

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
