"""Menú oculto (Ctrl+P): mantenimiento sin botones visibles en la interfaz.

Opciones:
- **Cambiar clave maestra** (el atajo oculto original).
- **Borrar base de datos y órdenes**: reinicia TODOS los datos operativos
  (ventas y órdenes, sesiones de caja, kardex, lotes, listas de compras y
  alertas atendidas; el stock vuelve a 0). Pide confirmación escribiendo
  «BORRAR» y crea un respaldo automático de seguridad antes de borrar.
  Conserva catálogo, insumos, ajustes y clave maestra.
"""
from __future__ import annotations

from qfluentwidgets import (
    BodyLabel,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from app.ui.common import COLOR_ERROR


class ConfirmWipeBox(MessageBoxBase):
    """Confirmación de borrado total: exige escribir «BORRAR»."""

    CONFIRM_WORD = "BORRAR"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("¿Borrar toda la base de datos y órdenes?")
        self.viewLayout.addWidget(self.titleLabel)

        self.bodyLabel = BodyLabel(
            "Se eliminarán:\n"
            "  · Ventas y órdenes (todas)\n"
            "  · Sesiones de caja y tickets emitidos\n"
            "  · Kardex, lotes y movimientos de inventario\n"
            "  · Listas de compras y alertas atendidas\n\n"
            "El stock de los insumos se reinicia a 0.\n"
            "Se conservan: catálogo, insumos, ajustes y clave maestra.\n\n"
            "Antes de borrar se creará un respaldo automático de seguridad."
        )
        self.viewLayout.addWidget(self.bodyLabel)

        self.input = LineEdit(self)
        self.input.setPlaceholderText(f"Escribe {self.CONFIRM_WORD} para confirmar")
        self.input.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.input)
        self.input.textChanged.connect(self._check_input)

        self.yesButton.setText("Borrar ahora")
        self.cancelButton.setText("Cancelar")
        self.yesButton.setEnabled(False)
        self.widget.setMinimumWidth(460)

    def _check_input(self) -> None:
        self.yesButton.setEnabled(
            self.input.text().strip() == self.CONFIRM_WORD)

    def validate(self) -> bool:
        return self.input.text().strip() == self.CONFIRM_WORD


class HiddenMenuDialog(MessageBoxBase):
    """Menú oculto de mantenimiento (Ctrl+P, sin botón en la interfaz)."""

    # Señales que refrescan la UI tras el borrado de datos
    REFRESH_SIGNALS = (
        "salesChanged",
        "cashSessionChanged",
        "movementsChanged",
        "lotsChanged",
        "shoppingListChanged",
        "ingredientsChanged",
    )

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx

        self.titleLabel = SubtitleLabel("Menú oculto")
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(BodyLabel(
            "Opciones de mantenimiento — no aparecen en ningún menú (Ctrl+P)"))

        key_button = PrimaryPushButton("Cambiar clave maestra")
        key_button.clicked.connect(self._change_key)
        self.viewLayout.addWidget(key_button)

        wipe_button = PushButton("Borrar base de datos y órdenes")
        wipe_button.setStyleSheet(
            f"PushButton {{ background-color: {COLOR_ERROR}; color: white;"
            f"    border: none; border-radius: 6px; }}"
            f"PushButton:hover {{ background-color: {COLOR_ERROR}; }}"
            f"PushButton:pressed {{ background-color: {COLOR_ERROR}; }}"
        )
        wipe_button.clicked.connect(self._wipe_data)
        self.viewLayout.addWidget(wipe_button)

        self.viewLayout.addWidget(BodyLabel(
            "El borrado crea un respaldo de seguridad antes de eliminar.\n"
            "Las acciones quedan registradas en data/logs/app.log"))

        self.yesButton.hide()
        self.cancelButton.setText("Cerrar")
        self.widget.setMinimumWidth(460)

    # ------------------------------------------------------------------

    def _change_key(self) -> None:
        from app.ui.dialogs.security_dialogs import ChangePasswordDialog

        ChangePasswordDialog(self.ctx, self.window()).exec()

    def _wipe_data(self) -> None:
        """Respaldo previo + borrado operativo + refresco de toda la UI."""
        if not ConfirmWipeBox(self.window()).exec():
            return

        backup_name = ""
        try:
            backup = self.ctx.backup.backup_now("pre-borrar")
            backup_name = backup.name
        except Exception:
            # El borrado no depende del respaldo, pero se intenta siempre
            backup_name = ""

        from app.core.services.maintenance_service import reset_operational_data

        reset_operational_data(self.ctx.db)

        # Actualizar todas las vistas abiertas (POS, inventario, listas…)
        for signal_name in self.REFRESH_SIGNALS:
            try:
                getattr(self.ctx.bus, signal_name).emit()
            except AttributeError:
                pass

        content = ("Ventas, órdenes, caja, kardex, lotes y listas de compras "
                   "fueron eliminados. El stock quedó en 0.")
        if backup_name:
            content += f"\nRespaldo de seguridad: {backup_name}"
        InfoBar.success(
            title="Base de datos reiniciada",
            content=content,
            parent=self.window(),
            position=InfoBarPosition.TOP,
            duration=7000,
        )
        self.accept()
