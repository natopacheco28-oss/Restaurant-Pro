"""Ventana principal de Restaurante Pro.

Ventana Fluent (qfluentwidgets.FluentWindow) con navegación lateral:
Caja · Catálogo · Inventario · Estadísticas · Ajustes.

Incluye:
- Campana del centro de notificaciones en la barra lateral, encima del
  engrane de Ajustes, con insignia de contador; revisión periódica
  (QTimer configurable en Ajustes), resumen al abrir el programa, alertas
  con InfoBar y notificación de la bandeja de Windows si el programa está
  minimizado (opcional).
- Atajo OCULTO Ctrl+P → menú de mantenimiento (sin botones visibles):
  cambiar la clave maestra o borrar la base de datos y las órdenes
  (con respaldo previo y confirmación).
- Cierre seguro: bloquea el modo edición y crea el respaldo automático.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from qfluentwidgets import FluentWindow, InfoBar, InfoBarPosition, NavigationItemPosition

from app.ui.common import COLOR_ERROR, fi
from app.version import APP_NAME

# Frecuencia de revisión de alertas por omisión (minutos)
DEFAULT_ALERT_INTERVAL_MIN = 30


class BellBadge(QLabel):
    """Insignia de contador de alertas sobre un ítem de la barra lateral."""

    def __init__(self, anchor: QWidget):
        super().__init__(anchor)
        self._anchor = anchor
        self.setFixedSize(18, 18)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background-color: {COLOR_ERROR}; color: white;"
            f"border-radius: 9px; font-size: 11px; font-weight: bold;")
        self.hide()

    def reposition(self) -> None:
        self.move(self._anchor.width() - 16, 1)

    def set_count(self, count: int) -> None:
        count = int(count)
        self.setVisible(count > 0)
        self.setText("99+" if count > 99 else str(count))
        self.reposition()


class MainWindow(FluentWindow):
    """Ventana raíz con navegación lateral Fluent."""

    def __init__(self, ctx):
        # El eventFilter de la barra sin marco puede dispararse desde el
        # propio constructor de FluentWindow: los atributos deben existir ya.
        self._bell_item = None
        self._bell_badge = None
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self._load_icon())
        self.setMinimumSize(1180, 760)
        self.resize(1440, 900)

        self._build_navigation()
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

        # Campana de notificaciones: al agregarse ANTES del engrane en la
        # zona inferior de la barra lateral queda ENCIMA de «Ajustes».
        self.navigationInterface.addItem(
            routeKey="alertas",
            icon=fi("BELL", "INFO", "MAIL"),
            text="Notificaciones",
            onClick=self._open_notifications,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
            tooltip="Notificaciones del almacén",
        )
        try:
            self._bell_item = self.navigationInterface.panel.widget("alertas")
        except Exception:
            self._bell_item = None
        self._bell_badge = BellBadge(self._bell_item) if self._bell_item else None
        if self._bell_item is not None:
            self._bell_item.installEventFilter(self)

        self.settings_module = SettingsModule(self.ctx)
        self.addSubInterface(
            self.settings_module,
            fi("SETTING"),
            "Ajustes",
            position=NavigationItemPosition.BOTTOM,
        )

    def eventFilter(self, obj, event):  # noqa: N802 (Qt)
        """Mantiene la insignia pegada a la esquina del ítem campana."""
        if (self._bell_item is not None and obj is self._bell_item
                and event.type() == QEvent.Type.Resize
                and self._bell_badge is not None):
            self._bell_badge.reposition()
        return super().eventFilter(obj, event)

    def _build_hidden_shortcuts(self) -> None:
        """Ctrl+P → menú oculto de mantenimiento (sin botón visible)."""
        self._change_key_shortcut = QShortcut(QKeySequence("Ctrl+P"), self)
        self._change_key_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._change_key_shortcut.activated.connect(self._open_hidden_menu)

    def _open_hidden_menu(self) -> None:
        """Menú oculto: clave maestra y borrado de base de datos/órdenes."""
        from app.ui.dialogs.hidden_menu_dialog import HiddenMenuDialog

        HiddenMenuDialog(self.ctx, self).exec()

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

    def _collect_alerts(self) -> list[dict]:
        alerts = self.ctx.alerts.collect()
        self._set_bell_count(len(alerts))
        return alerts

    def _set_bell_count(self, count: int) -> None:
        """Insignia y descripción de la campana en la barra lateral."""
        if self._bell_badge is not None:
            self._bell_badge.set_count(count)
        if self._bell_item is not None:
            self._bell_item.setToolTip(
                f"Notificaciones del almacén ({count})"
                if count else "Notificaciones del almacén — sin alertas")

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
        """Abre el centro de notificaciones (campana de la barra lateral)."""
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
