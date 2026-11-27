"""Diálogos de seguridad: desbloqueo de edición y cambio de clave maestra.

- `UnlockDialog`: pide la clave UNA VEZ por sesión para poder editar
  Catálogo/Inventario; aplica el retraso progresivo con cuenta regresiva.
- `ChangePasswordDialog`: menú oculto (Ctrl+P) para cambiar la clave
  maestra — pide la clave actual y la nueva con confirmación.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QWidget,
)

from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    PasswordLineEdit,
    SubtitleLabel,
)

MIN_KEY_LEN = 4


class _SecurityDialogBase(MessageBoxBase):
    """Base común: título, entradas ocultas y manejo del retraso progresivo."""

    def __init__(self, ctx, parent: QWidget):
        super().__init__(parent)
        self.ctx = ctx
        self._result: object = None
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)

    # -- helpers --------------------------------------------------------

    def _add_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        grid.setHorizontalSpacing(12)
        self.viewLayout.addLayout(grid)
        return grid

    def _show_error(self, message: str, wait_seconds: float = 0.0) -> None:
        text = message
        if wait_seconds > 0:
            text += f" Reintente en {int(wait_seconds)} s."
        InfoBar.error(
            title="Acceso denegado",
            content=text,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=4000,
        )
        if wait_seconds > 0:
            self._start_countdown(wait_seconds)

    def _start_countdown(self, seconds: float) -> None:
        """Desactiva las entradas mientras corre el retraso progresivo."""
        self._remaining = int(seconds) + 1
        for editor in self._password_editors():
            editor.setEnabled(False)
        self._tick_countdown()
        self._countdown_timer.start()

    def _tick_countdown(self) -> None:
        self._remaining = max(0, getattr(self, "_remaining", 0) - 1)
        for editor in self._password_editors():
            placeholder = (f"Esperando {self._remaining} s…"
                           if self._remaining else editor.placeholder_original)
            editor.setPlaceholderText(placeholder)
        if self._remaining <= 0:
            self._countdown_timer.stop()
            for editor in self._password_editors():
                editor.setEnabled(True)
                editor.setPlaceholderText(editor.placeholder_original)
                editor.clear()

    def _clear_inputs(self) -> None:
        for editor in self._password_editors():
            editor.clear()

    @staticmethod
    def _track_placeholder(editor: PasswordLineEdit) -> PasswordLineEdit:
        """Guarda el placeholder original para restaurarlo tras el bloqueo."""
        editor.placeholder_original = editor.placeholderText()
        return editor


class UnlockDialog(_SecurityDialogBase):
    """Pide la clave maestra para activar el modo edición de la sesión."""

    def __init__(self, ctx, parent: QWidget):
        super().__init__(ctx, parent)
        self.setWindowTitle("Desbloquear edición")

        title = SubtitleLabel("Modo edición")
        caption = CaptionLabel(
            "Ingrese la clave maestra para editar el catálogo y el inventario. "
            "Solo se pedirá una vez por sesión."
        )
        caption.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(caption)

        grid = self._add_grid()
        self._key_edit = self._track_placeholder(PasswordLineEdit())
        self._key_edit.setPlaceholderText("Clave maestra")
        self._key_edit.setMinimumWidth(280)
        grid.addWidget(QLabel("Clave:"), 0, 0)
        grid.addWidget(self._key_edit, 0, 1)

        self.yesButton.setText("Desbloquear")
        self.cancelButton.setText("Cancelar")
        self._key_edit.returnPressed.connect(self.yesButton.click)
        self._key_edit.setFocus()

    def _password_editors(self) -> list[PasswordLineEdit]:
        return [self._key_edit]

    def validate(self) -> bool:
        """Se ejecuta al pulsar «Desbloquear»: valida y activa el modo."""
        result = self.ctx.security.unlock(self._key_edit.text())
        if result.ok:
            self._result = True
            return True
        self._clear_inputs()
        self._show_error(result.message, result.wait_seconds)
        return False

    @property
    def unlocked(self) -> bool:
        return bool(self._result)


class ChangePasswordDialog(_SecurityDialogBase):
    """Cambio de clave maestra — se abre SOLO con Ctrl+P (menú oculto)."""

    def __init__(self, ctx, parent: QWidget):
        super().__init__(ctx, parent)
        self.setWindowTitle("Cambiar clave maestra")

        title = SubtitleLabel("Cambiar clave maestra")
        caption = CaptionLabel(
            "Escriba la clave actual y defina la nueva. La clave se guarda "
            "como hash PBKDF2 con sal, nunca en texto plano."
        )
        caption.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(caption)

        grid = self._add_grid()
        self._current_edit = self._track_placeholder(PasswordLineEdit())
        self._current_edit.setPlaceholderText("Clave actual")
        self._new_edit = self._track_placeholder(PasswordLineEdit())
        self._new_edit.setPlaceholderText(f"Nueva clave (mín. {MIN_KEY_LEN} caracteres)")
        self._confirm_edit = self._track_placeholder(PasswordLineEdit())
        self._confirm_edit.setPlaceholderText("Confirmar nueva clave")

        grid.addWidget(QLabel("Actual:"), 0, 0)
        grid.addWidget(self._current_edit, 0, 1)
        grid.addWidget(QLabel("Nueva:"), 1, 0)
        grid.addWidget(self._new_edit, 1, 1)
        grid.addWidget(QLabel("Confirmar:"), 2, 0)
        grid.addWidget(self._confirm_edit, 2, 1)

        for editor in self._password_editors():
            editor.setMinimumWidth(280)

        self.yesButton.setText("Guardar")
        self.cancelButton.setText("Cancelar")

    def _password_editors(self) -> list[PasswordLineEdit]:
        return [self._current_edit, self._new_edit, self._confirm_edit]

    def validate(self) -> bool:
        result = self.ctx.security.change_password(
            self._current_edit.text(),
            self._new_edit.text(),
            self._confirm_edit.text(),
        )
        if result.ok:
            self._result = True
            InfoBar.success(
                title="Clave actualizada",
                content="La nueva clave maestra está activa.",
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return True
        self._clear_inputs()
        self._show_error(result.message, result.wait_seconds)
        return False
