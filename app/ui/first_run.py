"""Asistente de bienvenida (PRIMER ARRANQUE).

Solo aparece cuando no hay clave maestra configurada. En dos pasos:
1) Bienvenida + nombre del restaurante (opcional, editable en Ajustes).
2) Definición de la clave maestra (entrada oculta + confirmación) que se
   guarda como hash PBKDF2 con sal — nunca en texto plano.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TitleLabel,
)

from app.version import APP_NAME, APP_VERSION


class FirstRunWizard(QDialog):
    """Asistente de configuración inicial (clave maestra)."""

    STEP_WELCOME = 0
    STEP_KEY = 1

    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(f"Bienvenido a {APP_NAME}")
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setFixedSize(560, 540)

        self._build_ui()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 28, 36, 24)
        root.setSpacing(12)

        # Logo + título
        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from app.ui.common import load_logo_pixmap

        logo.setPixmap(load_logo_pixmap(self.ctx.settings, 120))
        root.addWidget(logo)

        title = TitleLabel(f"Bienvenido a {APP_NAME}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        subtitle = CaptionLabel(
            f"Punto de venta y administración para restaurantes · v{APP_VERSION}"
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(subtitle)

        # Pasos del asistente
        self._stack = QStackedWidget()
        self._stack.addWidget(self._welcome_step())
        self._stack.addWidget(self._key_step())
        root.addWidget(self._stack, 1)

        # Navegación
        buttons = QHBoxLayout()
        self._back_button = PushButton("Atrás")
        self._back_button.setVisible(False)
        self._next_button = PrimaryPushButton("Comenzar")
        buttons.addStretch(1)
        buttons.addWidget(self._back_button)
        buttons.addWidget(self._next_button)
        root.addLayout(buttons)

        self._back_button.clicked.connect(self._go_back)
        self._next_button.clicked.connect(self._go_next)
        self._error_label = CaptionLabel("")
        self._error_label.setStyleSheet("color: #d13438;")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._error_label)

    def _welcome_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        text = BodyLabel(
            "Este asistente dejará listo el sistema en un minuto. Definirá la "
            "clave maestra que protege la edición del catálogo y del inventario.\n\n"
            "Toda la información (ventas, inventario y respaldos) se guarda junto "
            "al programa, en las carpetas «data» y «backups»: el sistema es 100% "
            "portable, igual que ABCell Pro."
        )
        text.setWordWrap(True)
        layout.addWidget(text)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText(
            self.ctx.settings.get("restaurant.name", "Mi Restaurante")
        )
        self._phone_edit = LineEdit()
        self._phone_edit.setPlaceholderText("Opcional")
        form.addRow("Nombre del restaurante:", self._name_edit)
        form.addRow("Teléfono:", self._phone_edit)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _key_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        heading = SubtitleLabel("Cree su clave maestra")
        layout.addWidget(heading)

        text = BodyLabel(
            "La clave protege las ediciones del catálogo y del inventario. "
            "Guárdela bien: se almacena solo como hash con sal y no existe "
            "recuperación automática."
        )
        text.setWordWrap(True)
        layout.addWidget(text)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._key_edit = PasswordLineEdit()
        self._key_edit.setPlaceholderText("Mínimo 4 caracteres")
        self._confirm_edit = PasswordLineEdit()
        self._confirm_edit.setPlaceholderText("Repita la clave")
        form.addRow("Clave maestra:", self._key_edit)
        form.addRow("Confirmar:", self._confirm_edit)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------

    def _go_back(self) -> None:
        self._error_label.setText("")
        self._stack.setCurrentIndex(self.STEP_WELCOME)
        self._back_button.setVisible(False)
        self._next_button.setText("Comenzar")

    def _go_next(self) -> None:
        self._error_label.setText("")
        if self._stack.currentIndex() == self.STEP_WELCOME:
            self._stack.setCurrentIndex(self.STEP_KEY)
            self._back_button.setVisible(True)
            self._next_button.setText("Finalizar")
            self._key_edit.setFocus()
            return

        # Validación y guardado de la clave maestra
        password = self._key_edit.text()
        confirm_password = self._confirm_edit.text()
        try:
            self.ctx.security.configure(password, confirm_password)
        except ValueError as exc:
            self._error_label.setText(str(exc))
            return

        # Datos opcionales del restaurante capturados en el paso 1
        name = self._name_edit.text().strip()
        if name:
            self.ctx.settings.set("restaurant.name", name)
        phone = self._phone_edit.text().strip()
        if phone:
            self.ctx.settings.set("restaurant.phone", phone)
        self.ctx.settings.save()
        self.ctx.bus.settingsChanged.emit()

        self.accept()
