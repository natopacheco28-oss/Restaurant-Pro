"""Widgets y utilidades de UI compartidos por todos los módulos."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CaptionLabel,
    FluentIcon,
    MessageBox,
    SimpleCardWidget,
    SubtitleLabel,
    TransparentPushButton,
)

from app.printing.ticket_builder import money


# ----------------------------------------------------------------------
# Iconos Fluent con tolerancia a versiones
# ----------------------------------------------------------------------

def fi(*names: str) -> FluentIcon:
    """Resuelve el primer icono FluentIcon existente en la versión instalada.

    Permite usar iconos nuevos sin romper en versiones antiguas de
    qfluentwidgets: `fi("SHOPPING_CART", "SELL")`.
    """
    for name in names:
        if hasattr(FluentIcon, name):
            return getattr(FluentIcon, name)
    return FluentIcon.HOME


# ----------------------------------------------------------------------
# Formato
# ----------------------------------------------------------------------

def format_dt(text: str) -> str:
    """'2025-01-01 13:45:00' → '01/01/2025 13:45'."""
    try:
        date, time = str(text).split(" ")
        year, month, day = date.split("-")
        return f"{day}/{month}/{year} {time[:5]}"
    except (ValueError, IndexError):
        return str(text)


def currency_of(settings) -> str:
    return str(settings.get("ticket.currency", "$") or "$")


# ----------------------------------------------------------------------
# Logo / placeholders
# ----------------------------------------------------------------------

def load_logo_pixmap(settings, size: int = 96) -> QPixmap:
    """Devuelve el logo configurado (o el de assets) escalado.

    Si no existe ningún archivo de logo, dibuja un marcador con el nombre de
    la app para que la UI nunca se vea rota (y el usuario es avisado).
    """
    import os

    from app.core.paths import logo_asset_path, resolve_portable

    candidates = []
    custom = settings.get("restaurant.logo_path", "") if settings else ""
    if custom:
        candidates.append(resolve_portable(custom))
    candidates.append(logo_asset_path())

    for path in candidates:
        if path and os.path.exists(path):
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                return pixmap.scaled(
                    size, size, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

    return placeholder_logo(size)


def placeholder_logo(size: int = 96) -> QPixmap:
    """Marcador visual cuando falta assets/logo.png (aviso al usuario)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#ff7a1a"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, size - 8, size - 8)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Segoe UI", max(8, size // 6), QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "RP")
    painter.end()
    return pixmap


# ----------------------------------------------------------------------
# Banner de modo edición (Catálogo / Inventario)
# ----------------------------------------------------------------------

class EditModeBanner(QWidget):
    """Indicador visible del modo edición con botón para bloquear.

    Estado bloqueado → botón "Desbloquear edición" (pide la clave maestra).
    Estado activo   → etiqueta verde "Modo edición activo" + "Bloquear".
    """

    def __init__(self, ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ctx = ctx
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(18, 18)
        self._status_label = CaptionLabel("Edición bloqueada")
        self._toggle_button = TransparentPushButton()

        self._layout.addWidget(self._icon_label)
        self._layout.addWidget(self._status_label)
        self._layout.addSpacing(4)
        self._layout.addWidget(self._toggle_button)
        self._layout.addStretch(1)

        self._toggle_button.clicked.connect(self._toggle)
        self.ctx.bus.editModeChanged.connect(lambda _: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        unlocked = self.ctx.security.is_unlocked
        if unlocked:
            self._status_label.setText("Modo edición activo — puede modificar catálogo e inventario")
            self._status_label.setStyleSheet("color: #22a06b; font-weight: 600;")
            self._toggle_button.setText("Bloquear")
            self._toggle_button.setIcon(fi("CLOSE", "CANCEL"))
            self._icon_label.setText("🔓")
        else:
            self._status_label.setText("Edición bloqueada — se requiere la clave maestra")
            self._status_label.setStyleSheet("color: #98989d;")
            self._toggle_button.setText("Desbloquear edición")
            self._toggle_button.setIcon(fi("UNLOCK", "CERTIFICATE", "EDIT"))
            self._icon_label.setText("🔒")

    def _toggle(self) -> None:
        if self.ctx.security.is_unlocked:
            self.ctx.security.lock()
            return
        # Import diferido para evitar ciclos con los diálogos
        from app.ui.dialogs.security_dialogs import UnlockDialog

        UnlockDialog(self.ctx, self.window()).exec()

    def is_unlocked(self) -> bool:
        return self.ctx.security.is_unlocked


# ----------------------------------------------------------------------
# Tarjetas reutilizables
# ----------------------------------------------------------------------

class KPICard(SimpleCardWidget):
    """Tarjeta de indicador clave (total vendido, tickets, promedio…)."""

    def __init__(self, title: str, value: str = "—", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(96)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        self._title = CaptionLabel(title.upper())
        self._value = BodyLabel(value)
        font = self._value.font()
        font.setPointSize(20)
        font.setBold(True)
        self._value.setFont(font)
        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addStretch(1)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


class SettingRow(CardWidget):
    """Fila de ajustes estilo Fluent: título + descripción + control a la derecha."""

    def __init__(self, title: str, description: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(56)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(16)

        text_box = QVBoxLayout()
        self._title_label = BodyLabel(title)
        self._title_label.setFont(QFont(self._title_label.font().family(), 11))
        text_box.addWidget(self._title_label)
        if description:
            desc = CaptionLabel(description)
            desc.setWordWrap(True)
            text_box.addWidget(desc)
        self._title_label.setWordWrap(True)

        layout.addLayout(text_box, 1)
        self._slot: Optional[QWidget] = None

    def set_widget(self, widget: QWidget) -> None:
        self._slot = widget
        self.layout().addWidget(widget)


# ----------------------------------------------------------------------
# Tarjeta de producto para la cuadrícula de la caja
# ----------------------------------------------------------------------

class ProductCard(CardWidget):
    """Producto de la cuadrícula: imagen (o inicial), nombre y precio."""

    clicked = Signal(dict)

    CARD_W, CARD_H = 168, 190
    THUMB_H = 104

    def __init__(self, product: dict, settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.product = product
        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if not product.get("available", True):
            self.setEnabled(False)
            self.setToolTip("Producto no disponible")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._thumb = QLabel()
        self._thumb.setFixedHeight(self.THUMB_H)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setPixmap(self._build_thumbnail(settings))
        layout.addWidget(self._thumb)

        name = BodyLabel(str(product["name"]))
        name.setWordWrap(True)
        name.setFont(QFont(name.font().family(), 10))
        layout.addWidget(name, 1)

        price = money(float(product["price"]), currency_of(settings))
        price_label = SubtitleLabel(price)
        price_label.setStyleSheet("color: #ff7a1a;")
        layout.addWidget(price_label)

    def _build_thumbnail(self, settings) -> QPixmap:
        """Imagen del producto o marcador con la inicial del nombre."""
        from app.core.paths import resolve_portable

        image = self.product.get("image") or ""
        if image:
            path = resolve_portable(image)
            if path.exists():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    return pixmap.scaled(
                        self.CARD_W - 20, self.THUMB_H,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
        # Marcador: círculo con la inicial
        size = self.THUMB_H - 16
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#ff7a1a") if self.product.get("available", True) else QColor("#98989d")
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, size, size)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Segoe UI", int(size * 0.4), QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter,
                         str(self.product["name"])[:1].upper())
        painter.end()
        return pixmap

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.product)
        super().mouseReleaseEvent(event)


# ----------------------------------------------------------------------
# Diálogo de confirmación estándar
# ----------------------------------------------------------------------

def confirm(parent, title: str, content: str) -> bool:
    """MessageBox de confirmación Sí/No con estilo Fluent."""
    box = MessageBox(title, content, parent)
    return bool(box.exec())


# ----------------------------------------------------------------------
# Ayudante para SegmentedWidget con tolerancia a versiones
# ----------------------------------------------------------------------

def make_segmented(items: list[tuple[str, str]], current: str,
                   on_change: Callable[[str], None], parent=None) -> QWidget:
    """Crea un SegmentedWidget (o ComboBox de respaldo) con los ítems dados.

    `items`: [(clave, etiqueta), …] · `on_change(clave)` al cambiar.
    """
    from qfluentwidgets import SegmentedWidget

    try:
        seg = SegmentedWidget(parent)
        for key, label in items:
            seg.addItem(routeKey=key, text=label, onClick=lambda k=key: on_change(k))
        seg.setCurrentItem(current)
        return seg
    except (AttributeError, TypeError):
        # Respaldo para versiones muy antiguas de qfluentwidgets
        from qfluentwidgets import ComboBox

        combo = ComboBox(parent)
        for _, label in items:
            combo.addItem(label)
        combo.setCurrentIndex(max(0, [k for k, _ in items].index(current)))
        combo.currentIndexChanged.connect(
            lambda idx: on_change(items[idx][0])
        )
        return combo
