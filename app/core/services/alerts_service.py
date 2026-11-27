"""Servicio de NOTIFICACIONES del almacén.

Reúne las alertas activas de tres tipos:
- stock bajo / agotado (`low:{id}`)
- lote vencido / por caducar (`exp:{lote}`)
- insumo sin movimiento (`stale:{id}`)

Soporta «atendida» y «posponer»:
- Atendida: la alerta no vuelve a mostrarse MIENTRAS la condición no cambie
  (se guarda una "foto" de la condición: stock actual, días restantes o días
  estancados). Si la condición cambia (ej. el stock baja más), vuelve a
  notificarse.
- Pospuesta: se oculta hasta `snooze_until`; al expirar reaparece.

El resumen de arranque ("Hoy: 3 por caducar, 5 en stock bajo") lo produce
`summary()`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.core.database import Database
from app.core.services.inventory_service import InventoryService

DEFAULT_SNOOZE_MINUTES = 60

# Orden de urgencia para presentar las alertas
SEVERITY_ORDER = {
    "agotado": 0,
    "vencido": 1,
    "por_caducar": 2,
    "bajo": 3,
    "estancado": 4,
}


class AlertsService:
    """Detecta alertas y administra atendidas/pospuestas."""

    def __init__(self, db: Database, inventory: InventoryService, settings=None):
        self.db = db
        self.inventory = inventory
        self.settings = settings

    # ------------------------------------------------------------------
    # Detección
    # ------------------------------------------------------------------

    def collect(self) -> list[dict]:
        """Alertas activas NO suprimidas (atendidas con condición igual o
        pospuestas vigentes), ordenadas por urgencia."""
        alerts: list[dict] = []

        # 1) Stock bajo / agotado
        if self._notify_enabled("notify_low", True):
            for ing in self.inventory.list_ingredients():
                estado = ing["estado"]
                if estado == "normal":
                    continue
                if estado == "agotado":
                    title, severity = "Insumo agotado", "agotado"
                else:
                    title, severity = "Stock bajo", "bajo"
                alerts.append(self._make(
                    key=f"low:{ing['id']}", kind="stock", title=title,
                    content=(f"«{ing['name']}»: {ing['stock']:g} {ing['unit']} en stock"
                             + (f" (mínimo {ing['min_stock']:g})" if ing["min_stock"] else "")),
                    ingredient_id=ing["id"], lot_id=None,
                    snapshot=f"{float(ing['stock']):.3f}", severity=severity,
                ))

        # 2) Caducidades (vencidos y por caducar)
        if self._notify_enabled("notify_expiry", True):
            for lot in self.inventory.list_lots(only_active=True):
                if not lot.get("expiration_date") or float(lot["quantity"]) <= 0:
                    continue
                days = int(lot["days_left"])
                if days < 0:
                    title, severity = "Lote vencido", "vencido"
                elif days <= int(lot["warn_days"]):
                    title, severity = "Lote por caducar", "por_caducar"
                else:
                    continue  # vigente: no alerta
                when = ("venció hace " + str(-days) + " d"
                        if days < 0 else f"en {days} día(s)")
                alerts.append(self._make(
                    key=f"exp:{lot['id']}", kind="expiry", title=title,
                    content=(f"«{lot['ingredient_name']}» lote {lot['lot_number']}: "
                             f"{float(lot['quantity']):g} {lot['unit']} {when} "
                             f"({lot['expiration_date']})"),
                    ingredient_id=lot["ingredient_id"], lot_id=lot["id"],
                    snapshot=str(days), severity=severity,
                ))

        # 3) Insumos sin movimiento (estancados)
        if self._notify_enabled("notify_stale", True):
            for ing in self.inventory.stale_ingredients():
                alerts.append(self._make(
                    key=f"stale:{ing['id']}", kind="stale", title="Sin movimiento",
                    content=(f"«{ing['name']}»: {ing['stock']:g} {ing['unit']} sin "
                             f"salidas hace {int(ing['days_stale'])} días — "
                             f"valor inmovilizado ${ing['value']:,.2f}"),
                    ingredient_id=ing["id"], lot_id=None,
                    snapshot=str(int(ing["days_stale"])), severity="estancado",
                ))

        # Aplicar supresión (atendidas con condición igual / pospuestas)
        active = [a for a in alerts if not self._suppressed(a)]
        active.sort(key=lambda a: SEVERITY_ORDER.get(a["severity"], 9))
        return active

    def _make(self, key: str, kind: str, title: str, content: str,
              ingredient_id: Optional[int], lot_id: Optional[int],
              snapshot: str, severity: str) -> dict:
        return {
            "key": key, "kind": kind, "title": title, "content": content,
            "ingredient_id": ingredient_id, "lot_id": lot_id,
            "snapshot": snapshot, "severity": severity,
        }

    # ------------------------------------------------------------------
    # Supresión (atendida / pospuesta)
    # ------------------------------------------------------------------

    def _suppressed(self, alert: dict) -> bool:
        """True si la alerta fue atendida (misma condición) o está pospuesta.

        Si la condición cambió respecto a la foto guardada, la fila se
        actualiza y la alerta vuelve a notificarse.
        """
        row = self.db.one(
            "SELECT * FROM alert_dismissals WHERE alert_key = ?", (alert["key"],)
        )
        if row is None:
            return False

        snooze_until = row["snooze_until"]
        if snooze_until:
            if snooze_until > datetime.now().isoformat(sep=" ")[:19]:
                return True  # sigue pospuesta
            # Pospuesta expirada: liberar
            self.db.execute("DELETE FROM alert_dismissals WHERE id = ?", (row["id"],))
            return False

        # Atendida: reaparece solo si la condición cambió
        if (row["condition_snapshot"] or "") != alert["snapshot"]:
            self.db.execute(
                """
                UPDATE alert_dismissals
                   SET condition_snapshot = ?,
                       dismissed_at = datetime('now', 'localtime')
                 WHERE id = ?
                """,
                (alert["snapshot"], row["id"]),
            )
            return False
        return True

    def dismiss(self, alert: dict) -> None:
        """«Atendida»: no vuelve a notificarse hasta que cambie la condición."""
        self.db.execute(
            """
            INSERT INTO alert_dismissals
                (alert_key, kind, condition_snapshot, dismissed_at, snooze_until)
            VALUES (?, ?, ?, datetime('now', 'localtime'), NULL)
            ON CONFLICT (alert_key) DO UPDATE SET
                kind = excluded.kind,
                condition_snapshot = excluded.condition_snapshot,
                dismissed_at = excluded.dismissed_at,
                snooze_until = NULL
            """,
            (alert["key"], alert["kind"], alert["snapshot"]),
        )

    def snooze(self, alert: dict, minutes: int = DEFAULT_SNOOZE_MINUTES) -> None:
        """«Pospuesta»: se oculta hasta `now + minutes`."""
        until = (datetime.now() + timedelta(minutes=int(minutes))).isoformat(
            sep=" ")[:19]
        self.db.execute(
            """
            INSERT INTO alert_dismissals
                (alert_key, kind, condition_snapshot, dismissed_at, snooze_until)
            VALUES (?, ?, ?, datetime('now', 'localtime'), ?)
            ON CONFLICT (alert_key) DO UPDATE SET
                kind = excluded.kind,
                condition_snapshot = excluded.condition_snapshot,
                snooze_until = excluded.snooze_until
            """,
            (alert["key"], alert["kind"], alert["snapshot"], until),
        )

    def clear_all(self) -> None:
        """Elimina todas las supresiones (todo vuelve a notificar)."""
        self.db.execute("DELETE FROM alert_dismissals")

    # ------------------------------------------------------------------
    # Resumen
    # ------------------------------------------------------------------

    @staticmethod
    def summary(alerts: list[dict]) -> str:
        """Texto «Hoy: 3 por caducar, 5 en stock bajo…» para el arranque."""
        counts: dict[str, int] = {}
        for alert in alerts:
            counts[alert["severity"]] = counts.get(alert["severity"], 0) + 1
        labels = {
            "vencido": ("vencido", "vencidos"),
            "por_caducar": ("por caducar", "por caducar"),
            "agotado": ("agotado", "agotados"),
            "bajo": ("en stock bajo", "en stock bajo"),
            "estancado": ("sin movimiento", "sin movimiento"),
        }
        order = ("vencido", "por_caducar", "agotado", "bajo", "estancado")
        parts = []
        for severity in order:
            count = counts.get(severity, 0)
            if count:
                singular, plural = labels[severity]
                noun = singular if count == 1 else plural
                parts.append(f"{count} {noun}")
        return "Hoy: " + (", ".join(parts) if parts else "sin alertas de almacén ✔")

    # ------------------------------------------------------------------

    def _notify_enabled(self, key: str, default: bool) -> bool:
        try:
            return bool(self.settings.get(f"inventory.{key}", default))
        except (AttributeError, TypeError):
            return default
