"""Módulo AJUSTES: restaurante, ticket e impresión, apariencia y respaldos.

Secciones:
1. Datos del restaurante (nombre, eslogan, teléfono, dirección, RFC,
   redes sociales, logo con vista previa) — se reflejan en los tickets.
2. Ticket e impresión (moneda, impuesto, propina sugerida, pie, políticas,
   papel 58/80 mm, impresora, método, corte de papel, cajón, prueba).
3. Apariencia (tema claro/oscuro/automático y color de acento).
4. Datos y respaldos (carpeta configurable, respaldar/restaurar).
5. Acerca de.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SimpleCardWidget,
    SubtitleLabel,
    TextEdit,
    TitleLabel,
    ToolButton,
)

from qfluentwidgets import setTheme, setThemeColor, Theme

from app.core.paths import (
    backups_default_dir,
    data_dir,
    images_dir,
    portable_path,
    resolve_portable,
)
from app.printing.ticket_builder import build_test_ticket_text
from app.ui.common import confirm, fi, load_logo_pixmap
from app.ui.dialogs.ticket_dialogs import TicketPreviewDialog


class SettingsModule(ScrollArea):
    """Página de ajustes con desplazamiento vertical."""

    def __init__(self, ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("SettingsModule")
        self.setWidgetResizable(True)
        self.setFrameShape(ScrollArea.Shape.NoFrame)
        if hasattr(self, "enableTransparentBackground"):
            self.enableTransparentBackground()

        holder = QWidget()
        root = QVBoxLayout(holder)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(14)

        root.addWidget(TitleLabel("Ajustes"))
        root.addWidget(self._restaurant_card())
        root.addWidget(self._ticket_card())
        root.addWidget(self._appearance_card())
        root.addWidget(self._data_card())
        root.addWidget(self._about_card())
        root.addStretch(1)

        self.setWidget(holder)
        self._load_values()

    # ==================================================================
    # 1. Datos del restaurante
    # ==================================================================

    def _restaurant_card(self) -> SimpleCardWidget:
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("Datos del restaurante"))
        layout.addWidget(CaptionLabel(
            "Estos datos aparecen en el encabezado de todos los tickets."))

        form = QVBoxLayout()
        self._name_edit = self._add_form_row(form, "Nombre:")
        self._slogan_edit = self._add_form_row(form, "Eslogan:")
        self._phone_edit = self._add_form_row(form, "Teléfono:")
        self._address_edit = self._add_form_row(form, "Dirección:")
        self._tax_id_edit = self._add_form_row(form, "RFC / dato fiscal:")
        self._social_edit = self._add_form_row(form, "Redes sociales:")
        self._policies_edit = TextEdit()
        self._policies_edit.setPlaceholderText(
            "Ej. Consumo en el salón no genera propina obligatoria…")
        self._policies_edit.setFixedHeight(64)
        form.addWidget(CaptionLabel("Políticas:"))
        form.addWidget(self._policies_edit)
        layout.addLayout(form)

        # Logo con vista previa
        logo_row = QHBoxLayout()
        self._logo_preview = QLabel()
        self._logo_preview.setFixedSize(88, 88)
        self._logo_preview.setStyleSheet(
            "border: 1px dashed #98989d; border-radius: 10px; background: transparent;")
        buttons_box = QVBoxLayout()
        pick_button = PushButton("Elegir logo…")
        pick_button.setIcon(fi("PHOTO", "IMAGE", "FOLDER"))
        pick_button.clicked.connect(self._pick_logo)
        reset_button = PushButton("Usar logo original")
        reset_button.clicked.connect(self._reset_logo)
        buttons_box.addWidget(pick_button)
        buttons_box.addWidget(reset_button)
        buttons_box.addStretch(1)
        logo_row.addWidget(self._logo_preview)
        logo_row.addSpacing(12)
        logo_row.addLayout(buttons_box, 1)
        layout.addLayout(logo_row)

        save = PrimaryPushButton("Guardar datos del restaurante")
        save.setIcon(fi("ACCEPT", "SAVE"))
        save.clicked.connect(self._save_restaurant)
        layout.addWidget(save)
        return card

    @staticmethod
    def _add_form_row(form: QVBoxLayout, label: str) -> LineEdit:
        row = QHBoxLayout()
        row.addWidget(CaptionLabel(label))
        edit = LineEdit()
        edit.setClearButtonEnabled(True)
        row.addWidget(edit, 1)
        form.addLayout(row)
        return edit

    def _pick_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir logo del restaurante", "",
            "Imágenes (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        images_dir().mkdir(parents=True, exist_ok=True)
        dest = images_dir() / f"logo_{uuid.uuid4().hex[:8]}{Path(path).suffix.lower()}"
        try:
            shutil.copy2(path, dest)
        except OSError as exc:
            InfoBar.error(title="No se pudo copiar el logo", content=str(exc),
                          parent=self, position=InfoBarPosition.TOP, duration=4000)
            return
        self.ctx.settings.set("restaurant.logo_path", portable_path(dest))
        self._refresh_logo_preview()
        self._notify("Logo actualizado", "Se usará en la pantalla y en los tickets.")

    def _reset_logo(self) -> None:
        self.ctx.settings.set("restaurant.logo_path", "")
        self._refresh_logo_preview()
        self._notify("Logo restablecido", "Se usa el logo original de assets.")

    def _refresh_logo_preview(self) -> None:
        self._logo_preview.setPixmap(load_logo_pixmap(self.ctx.settings, 88))

    def _save_restaurant(self) -> None:
        self.ctx.settings.update({
            "restaurant.name": self._name_edit.text().strip(),
            "restaurant.slogan": self._slogan_edit.text().strip(),
            "restaurant.phone": self._phone_edit.text().strip(),
            "restaurant.address": self._address_edit.text().strip(),
            "restaurant.tax_id": self._tax_id_edit.text().strip(),
            "restaurant.social": self._social_edit.text().strip(),
            "restaurant.policies": self._policies_edit.toPlainText().strip(),
        })
        self._notify("Datos guardados", "Los cambios se reflejarán en los tickets.")

    # ==================================================================
    # 2. Ticket e impresión
    # ==================================================================

    def _ticket_card(self) -> SimpleCardWidget:
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("Ticket e impresión"))

        money_row = QHBoxLayout()
        money_row.addWidget(CaptionLabel("Moneda:"))
        self._currency_edit = LineEdit()
        self._currency_edit.setFixedWidth(70)
        self._currency_edit.setPlaceholderText("$")
        money_row.addWidget(self._currency_edit)
        money_row.addSpacing(24)
        money_row.addWidget(CaptionLabel("Impuesto (%):"))
        self._tax_spin = DoubleSpinBox()
        self._tax_spin.setRange(0.0, 100.0)
        self._tax_spin.setDecimals(2)
        self._tax_spin.setFixedWidth(100)
        money_row.addWidget(self._tax_spin)
        money_row.addSpacing(24)
        money_row.addWidget(CaptionLabel("Propina sugerida (%):"))
        self._tip_spin = DoubleSpinBox()
        self._tip_spin.setRange(0.0, 50.0)
        self._tip_spin.setDecimals(1)
        self._tip_spin.setFixedWidth(100)
        money_row.addWidget(self._tip_spin)
        money_row.addStretch(1)
        layout.addLayout(money_row)

        footer_row = QVBoxLayout()
        footer_row.addWidget(CaptionLabel("Mensaje al pie del ticket:"))
        self._footer_edit = TextEdit()
        self._footer_edit.setFixedHeight(56)
        footer_row.addWidget(self._footer_edit)
        layout.addLayout(footer_row)

        # Papel 58/80 mm
        paper_row = QHBoxLayout()
        paper_row.addWidget(CaptionLabel("Papel de la impresora:"))
        self._paper_combo = ComboBox()
        self._paper_combo.addItem("58 mm (32 caracteres)", userData=32)
        self._paper_combo.addItem("80 mm (48 caracteres)", userData=48)
        paper_row.addWidget(self._paper_combo)
        paper_row.addStretch(1)
        layout.addLayout(paper_row)

        # Impresora
        printer_row = QHBoxLayout()
        printer_row.addWidget(CaptionLabel("Impresora:"))
        self._printer_combo = ComboBox()
        self._printer_combo.setMinimumWidth(260)
        printer_row.addWidget(self._printer_combo, 1)
        refresh_printers = ToolButton(fi("SYNC", "UPDATE"))
        refresh_printers.setToolTip("Buscar impresoras")
        refresh_printers.clicked.connect(self._reload_printers)
        printer_row.addWidget(refresh_printers)
        printer_row.addWidget(CaptionLabel("Método:"))
        self._method_combo = ComboBox()
        self._method_combo.addItem("Automático (RAW con respaldo)", userData="auto")
        self._method_combo.addItem("RAW / ESC-POS (térmicas)", userData="raw")
        self._method_combo.addItem("QPrinter (gráfico)", userData="qprinter")
        printer_row.addWidget(self._method_combo)
        layout.addLayout(printer_row)

        options_row = QHBoxLayout()
        self._logo_check = CheckBox("Imprimir logo")
        self._cut_check = CheckBox("Corte de papel")
        self._drawer_check = CheckBox("Abrir cajón monetario")
        self._autoprint_check = CheckBox("Imprimir ticket al cobrar")
        for check in (self._logo_check, self._cut_check, self._drawer_check,
                      self._autoprint_check):
            options_row.addWidget(check)
        options_row.addStretch(1)
        layout.addLayout(options_row)

        actions_row = QHBoxLayout()
        preview_button = PushButton("Vista previa del ticket")
        preview_button.setIcon(fi("VIEW", "ZOOM"))
        preview_button.clicked.connect(self._preview_ticket)
        test_button = PushButton("Imprimir prueba")
        test_button.setIcon(fi("PRINT", "DOCUMENT"))
        test_button.clicked.connect(self._print_test)
        actions_row.addWidget(preview_button)
        actions_row.addWidget(test_button)
        actions_row.addStretch(1)
        layout.addLayout(actions_row)

        save = PrimaryPushButton("Guardar ajustes de ticket")
        save.setIcon(fi("ACCEPT", "SAVE"))
        save.clicked.connect(self._save_ticket)
        layout.addWidget(save)
        return card

    def _reload_printers(self) -> None:
        from app.printing.printer import list_printers

        current = self.ctx.settings.get("ticket.printer_name", "")
        self._printer_combo.clear()
        self._printer_combo.addItem("— Sin impresora —", userData="")
        for name in list_printers():
            self._printer_combo.addItem(name, userData=name)
        index = self._printer_combo.findData(current)
        self._printer_combo.setCurrentIndex(max(index, 0))

    def _save_ticket(self) -> None:
        currency = self._currency_edit.text().strip() or "$"
        try:
            float(currency.replace(".", "").replace(",", ""))
        except ValueError:
            self._notify("Moneda inválida",
                         "Use un símbolo corto, por ejemplo $, MX$, € o S/.", error=True)
            return
        self.ctx.settings.update({
            "ticket.currency": currency,
            "ticket.tax_rate": self._tax_spin.value(),
            "ticket.tip_suggested": self._tip_spin.value(),
            "ticket.footer": self._footer_edit.toPlainText().strip(),
            "ticket.width_chars": self._paper_combo.currentData() or 48,
            "ticket.printer_name": self._printer_combo.currentData() or "",
            "ticket.print_method": self._method_combo.currentData() or "auto",
            "ticket.show_logo": self._logo_check.isChecked(),
            "ticket.auto_cut": self._cut_check.isChecked(),
            "ticket.open_drawer": self._drawer_check.isChecked(),
            "ticket.auto_print": self._autoprint_check.isChecked(),
        })
        self._notify("Ajustes de ticket guardados", "Se aplican desde el próximo ticket.")

    def _preview_ticket(self) -> None:
        """Vista previa del ticket con los ajustes actuales (sin cobrar)."""
        sale = {"folio": 1, "datetime": "—", "order_type": "mesa",
                "payment_method": "efectivo", "subtotal": 100.0, "discount": 0,
                "tax": self.ctx.settings.get("ticket.tax_rate", 0), "tip": 0,
                "total": 116.0, "paid": 200.0, "change": 84.0,
                "waiter": "Prueba", "customer": ""}
        items = [
            {"product_name": "Producto de ejemplo", "unit_price": 50.0, "quantity": 2,
             "note": "Sin cebolla"},
            {"product_name": "Bebida", "unit_price": 35.0, "quantity": 1, "note": ""},
        ]
        TicketPreviewDialog(self.ctx, sale, items, self.window()).exec()

    def _print_test(self) -> None:
        text = build_test_ticket_text(self.ctx.settings)
        logo = self.ctx.settings.get("restaurant.logo_path", "")
        from app.core.paths import logo_asset_path

        logo_path = str(resolve_portable(logo)) if logo else (
            str(logo_asset_path()) if logo_asset_path().exists() else None)
        ok, message = self.ctx.printer.print_sale_ticket(text, logo_path)
        self._notify("Prueba de impresión", message, error=not ok)

    # ==================================================================
    # 3. Apariencia
    # ==================================================================

    def _appearance_card(self) -> SimpleCardWidget:
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("Apariencia"))

        theme_row = QHBoxLayout()
        theme_row.addWidget(CaptionLabel("Tema:"))
        self._theme_combo = ComboBox()
        self._theme_combo.addItem("Automático (según Windows)", userData="auto")
        self._theme_combo.addItem("Claro", userData="light")
        self._theme_combo.addItem("Oscuro", userData="dark")
        self._theme_combo.currentIndexChanged.connect(self._apply_theme)
        theme_row.addWidget(self._theme_combo)
        theme_row.addSpacing(24)
        theme_row.addWidget(CaptionLabel("Color de acento:"))
        self._accent_button = PushButton("Elegir color…")
        self._accent_button.clicked.connect(self._pick_accent)
        theme_row.addWidget(self._accent_button)
        theme_row.addStretch(1)
        layout.addLayout(theme_row)
        return card

    def _apply_theme(self) -> None:
        value = self._theme_combo.currentData() or "auto"
        theme_map = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}
        try:
            setTheme(theme_map.get(value, Theme.AUTO))
        except Exception:  # pragma: no cover
            setTheme(Theme.LIGHT)
        self.ctx.settings.set("ui.theme", value)
        self._notify("Tema aplicado", f"Modo {value}.")

    def _pick_accent(self) -> None:
        color = self._accent_dialog()
        if color is None:
            return
        setThemeColor(color)
        self.ctx.settings.set("ui.accent", color)
        self._notify("Color de acento actualizado", color)

    @staticmethod
    def _accent_dialog() -> Optional[str]:
        try:
            from qfluentwidgets import ColorDialog
            from PySide6.QtGui import QColor

            dialog = ColorDialog(QColor("#ff7a1a"), None, enableAlpha=False)
            if dialog.exec():
                return dialog.color.name().upper()
            return None
        except ImportError:  # pragma: no cover
            from PySide6.QtWidgets import QColorDialog

            color = QColorDialog.getColor()
            return color.name().upper() if color.isValid() else None

    # ==================================================================
    # 4. Datos y respaldos
    # ==================================================================

    def _data_card(self) -> SimpleCardWidget:
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("Datos y respaldos"))
        layout.addWidget(CaptionLabel(
            f"Carpeta de datos portable: {data_dir()}"))

        backup_row = QHBoxLayout()
        backup_row.addWidget(CaptionLabel("Carpeta de respaldos:"))
        self._backup_dir_edit = LineEdit()
        self._backup_dir_edit.setPlaceholderText(str(backups_default_dir()))
        backup_row.addWidget(self._backup_dir_edit, 1)
        browse = PushButton("Explorar…")
        browse.clicked.connect(self._pick_backup_dir)
        backup_row.addWidget(browse)
        layout.addLayout(backup_row)

        buttons_row = QHBoxLayout()
        backup_now = PrimaryPushButton("Respaldar ahora")
        backup_now.setIcon(fi("SAVE", "COPY"))
        backup_now.clicked.connect(self._backup_now)
        restore = PushButton("Restaurar respaldo…")
        restore.setIcon(fi("RETURN", "ARROW_LEFT", "UPDATE"))
        restore.clicked.connect(self._restore_backup)
        open_folder = PushButton("Abrir carpeta de datos")
        open_folder.setIcon(fi("FOLDER"))
        open_folder.clicked.connect(self._open_data_folder)
        buttons_row.addWidget(backup_now)
        buttons_row.addWidget(restore)
        buttons_row.addWidget(open_folder)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)
        layout.addWidget(CaptionLabel(
            "Al cerrar el programa se crea un respaldo automático con fecha y "
            "hora; se conservan los últimos 10."))
        return card

    def _pick_backup_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Carpeta de respaldos", self._backup_dir_edit.text() or
            str(backups_default_dir()))
        if path:
            self._backup_dir_edit.setText(path)
            self.ctx.settings.set("paths.backup_dir", path)
            self._notify("Carpeta de respaldos actualizada", path)

    def _backup_now(self) -> None:
        try:
            backup = self.ctx.backup.backup_now("manual")
            self._notify("Respaldo creado", str(backup))
        except Exception as exc:
            self._notify("No se pudo respaldar", str(exc), error=True)

    def _restore_backup(self) -> None:
        backups = self.ctx.backup.list_backups()
        if not backups:
            self._notify("Sin respaldos", "Aún no hay respaldos para restaurar.",
                         error=True)
            return
        dialog = RestorePickerDialog(backups, self.window())
        if not dialog.exec() or dialog.selected is None:
            return
        backup = dialog.selected
        if not confirm(
            self, "Restaurar respaldo",
            f"¿Restaurar «{backup.name}»? La base actual se respalda primero y "
            f"la aplicación se cerrará para aplicar los cambios.",
        ):
            return
        try:
            pre_restore = self.ctx.backup.restore(backup)
            self.ctx.db.reopen()
        except Exception as exc:
            self._notify("No se pudo restaurar", str(exc), error=True)
            return
        self._notify("Respaldo restaurado",
                     f"Copia previa: {pre_restore.name}. La aplicación se cerrará.")
        self.window().close()

    def _open_data_folder(self) -> None:
        import subprocess
        import sys

        path = str(data_dir())
        if sys.platform == "win32":
            subprocess.Popen(["explorer", path])
        else:  # pragma: no cover (solo desarrollo)
            subprocess.Popen(["xdg-open", path])

    # ==================================================================
    # 5. Acerca de
    # ==================================================================

    def _about_card(self) -> SimpleCardWidget:
        from app.version import APP_NAME, APP_VERSION

        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        layout.addWidget(SubtitleLabel(f"{APP_NAME} v{APP_VERSION}"))
        layout.addWidget(CaptionLabel(
            "Punto de venta y administración para restaurantes con la misma "
            "filosofía portable de ABCell Pro: un ejecutable, datos junto a él "
            "y respaldos locales. Interfaz Fluent Design (PySide6 + "
            "PySide6-Fluent-Widgets) sobre SQLite."))
        return card

    # ==================================================================
    # Carga / utilidades
    # ==================================================================

    def _load_values(self) -> None:
        s = self.ctx.settings
        self._name_edit.setText(s.get("restaurant.name", ""))
        self._slogan_edit.setText(s.get("restaurant.slogan", ""))
        self._phone_edit.setText(s.get("restaurant.phone", ""))
        self._address_edit.setText(s.get("restaurant.address", ""))
        self._tax_id_edit.setText(s.get("restaurant.tax_id", ""))
        self._social_edit.setText(s.get("restaurant.social", ""))
        self._policies_edit.setPlainText(s.get("restaurant.policies", ""))
        self._currency_edit.setText(s.get("ticket.currency", "$"))
        self._tax_spin.setValue(float(s.get("ticket.tax_rate", 16.0)))
        self._tip_spin.setValue(float(s.get("ticket.tip_suggested", 10.0)))
        self._footer_edit.setPlainText(s.get("ticket.footer", ""))
        self._paper_combo.setCurrentIndex(
            0 if int(s.get("ticket.width_chars", 48)) == 32 else 1)
        self._method_combo.setCurrentIndex(
            {"auto": 0, "raw": 1, "qprinter": 2}.get(
                str(s.get("ticket.print_method", "auto")), 0))
        self._logo_check.setChecked(bool(s.get("ticket.show_logo", True)))
        self._cut_check.setChecked(bool(s.get("ticket.auto_cut", True)))
        self._drawer_check.setChecked(bool(s.get("ticket.open_drawer", False)))
        self._autoprint_check.setChecked(bool(s.get("ticket.auto_print", True)))
        self._theme_combo.setCurrentIndex(
            {"auto": 0, "light": 1, "dark": 2}.get(str(s.get("ui.theme", "auto")), 0))
        self._backup_dir_edit.setText(s.get("paths.backup_dir", ""))
        self._reload_printers()
        self._refresh_logo_preview()

    def _notify(self, title: str, content: str, error: bool = False) -> None:
        factory = InfoBar.error if error else InfoBar.success
        factory(title=title, content=content, parent=self,
                position=InfoBarPosition.TOP, duration=4000)


class RestorePickerDialog(MessageBoxBase):
    """Selector de respaldo disponible."""

    def __init__(self, backups: list[Path], parent: QWidget):
        super().__init__(parent)
        self.selected: Optional[Path] = None

        self.viewLayout.addWidget(SubtitleLabel("Elegir respaldo"))
        self.viewLayout.addWidget(CaptionLabel(
            "Se conservan los últimos 10; el más reciente aparece arriba."))

        self._list = ComboBox()
        self._backups = backups
        for backup in backups:
            self._list.addItem(backup.name)
        self.viewLayout.addWidget(self._list)

        self.yesButton.setText("Restaurar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(420)

    def validate(self) -> bool:
        index = self._list.currentIndex()
        if 0 <= index < len(self._backups):
            self.selected = self._backups[index]
        return True
