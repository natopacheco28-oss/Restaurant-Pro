"""Centro de notificaciones del almacén (icono de campana de la barra superior).

Muestra la lista de alertas activas ordenadas por urgencia, con acciones
por alerta:
- «Ver»        → va directo al insumo en el módulo Inventario.
- «Posponer»   → oculta la alerta 1 hora (reaparece al expirar).
- «Atendida»   → no vuelve a notificarse hasta que cambie la condición.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    MessageBoxBase,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from app.ui.common import COLOR_ERROR, COLOR_OK, COLOR_WARN, fi

SEVERITY_TEXT = {
    "agotado": ("Agotado", COLOR_ERROR),
    "vencido": ("Vencido", COLOR_ERROR),
    "por_caducar": ("Por caducar", COLOR_WARN),
    "bajo": ("Stock bajo", COLOR_WARN),
    "estancado": ("Sin movimiento", COLOR_WARN),
}


class NotificationsDialog(MessageBoxBase):
    """Lista de alertas activas con acciones rápidas."""

    def __init__(self, ctx, parent: QWidget,
                 on_focus: Optional[Callable] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.on_focus = on_focus  # callback(ingredient_id) para «Ver»
        self._changed = False     # hubo posponer/atendida → refrescar badge

        self.viewLayout.addWidget(SubtitleLabel("Notificaciones del almacén"))
        self.viewLayout.addWidget(CaptionLabel(
            "Posponer oculta la alerta 1 hora; «Atendida» la silencia hasta "
            "que cambie la condición."))

        alerts = self.ctx.alerts.collect()
        self._alerts = alerts

        if not alerts:
            ok = QLabel("✔ Sin alertas de almacén")
            ok.setStyleSheet(f"color: {COLOR_OK}; font-weight: 600; padding: 16px;")
            ok.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.viewLayout.addWidget(ok)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            if hasattr(scroll, "enableTransparentBackground"):
                scroll.enableTransparentBackground()
            holder = QWidget()
            rows = QVBoxLayout(holder)
            rows.setContentsMargins(0, 0, 4, 0)
            rows.setSpacing(6)
            for alert in alerts:
                rows.addWidget(self._alert_row(alert))
            rows.addStretch(1)
            scroll.setWidget(holder)
            scroll.setMinimumSize(560, 340)
            self.viewLayout.addWidget(scroll)

            self.viewLayout.addWidget(CaptionLabel(
                self.ctx.alerts.summary(alerts)))

        self.yesButton.setText("Cerrar")
        self.cancelButton.hide()
        self.widget.setMinimumWidth(620)

    # ------------------------------------------------------------------

    def _alert_row(self, alert: dict) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        severity_text, color = SEVERITY_TEXT.get(
            alert["severity"], (alert["severity"], COLOR_WARN))
        dot = BodyLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 16px;")
        layout.addWidget(dot)

        text_box = QVBoxLayout()
        text_box.setSpacing(0)
        title = StrongBodyLabel(f"{alert['title']} · {severity_text}")
        title.setStyleSheet(f"color: {color};")
        text_box.addWidget(title)
        content = CaptionLabel(alert["content"])
        content.setWordWrap(True)
        text_box.addWidget(content)
        layout.addLayout(text_box, 1)

        if alert["ingredient_id"] and self.on_focus is not None:
            view_button = PushButton("Ver")
            view_button.setIcon(fi("VISIBILITY", "EYE", "CARE_RIGHT_SOLID"))
            view_button.setToolTip("Ir al insumo en Inventario")
            ingredient_id = alert["ingredient_id"]
            view_button.clicked.connect(
                lambda _=False, iid=ingredient_id: self._go(iid))
            layout.addWidget(view_button)

        snooze_button = PushButton("Posponer")
        snooze_button.clicked.connect(lambda _=False, a=alert: self._snooze(a))
        layout.addWidget(snooze_button)

        done_button = PushButton("Atendida")
        done_button.clicked.connect(lambda _=False, a=alert: self._dismiss(a))
        layout.addWidget(done_button)
        return row

    # ------------------------------------------------------------------

    def _go(self, ingredient_id: int) -> None:
        if self.on_focus is not None:
            self.on_focus(ingredient_id)
        self.accept()

    def _snooze(self, alert: dict) -> None:
        self.ctx.alerts.snooze(alert)
        self._changed = True
        self.accept()

    def _dismiss(self, alert: dict) -> None:
        self.ctx.alerts.dismiss(alert)
        self._changed = True
        self.accept()

    @property
    def changed(self) -> bool:
        return self._changed
