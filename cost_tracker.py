"""
cost_tracker.py — Tracking de gasto + kill switch + alertas de presupuesto.

Reglas (Haiku-only, barato):
- Safety stop: al llegar a DAILY_SAFETY_STOP_USD ($3) dejamos de scorear hoy.
- Techo duro: DAILY_HARD_CEILING_USD ($5) nunca debe superarse (defensa extra).
- Alerta acumulada: avisar a Telegram cada CUMULATIVE_ALERT_STEP_USD ($15).
- Alerta de saldo Anthropic agotado: la dispara main.py al cachar el error.

El estado vive en la base de datos (daily_stats.haiku_cost), así persiste
entre corridas de GitHub Actions.
"""

import config


class CostTracker:
    def __init__(self, db, telegram=None):
        self.db = db
        self.telegram = telegram  # puede ser None en tests
        self.run_cost = 0.0       # gasto de esta corrida
        self.run_calls = 0        # llamadas a Haiku en esta corrida

    # -- registro -----------------------------------------------------------
    def record(self, cost: float):
        """Registra el costo de una llamada (en DB y en memoria de la corrida)."""
        self.db.bump_stat("haiku_cost", cost)
        self.run_cost += cost
        self.run_calls += 1
        self._maybe_alert_cumulative()

    # -- gating -------------------------------------------------------------
    def can_spend(self) -> tuple[bool, str]:
        """¿Podemos hacer otra llamada a Haiku? (chequear ANTES de llamar)."""
        today = self.db.get_today_cost()

        if today >= config.DAILY_HARD_CEILING_USD:
            return False, f"hard_ceiling (${today:.2f} >= ${config.DAILY_HARD_CEILING_USD})"

        if today >= config.DAILY_SAFETY_STOP_USD:
            return False, f"safety_stop (${today:.2f} >= ${config.DAILY_SAFETY_STOP_USD})"

        if self.run_calls >= config.MAX_HAIKU_CALLS_PER_RUN:
            return False, f"max_calls_per_run ({config.MAX_HAIKU_CALLS_PER_RUN})"

        return True, "ok"

    # -- alertas ------------------------------------------------------------
    def _maybe_alert_cumulative(self):
        """Avisa a Telegram al cruzar cada múltiplo de $15 acumulado."""
        if self.telegram is None:
            return
        cumulative = self.db.get_cumulative_cost()
        step = config.CUMULATIVE_ALERT_STEP_USD
        if step <= 0:
            return
        milestone = int(cumulative // step) * step
        if milestone <= 0:
            return
        alert_key = f"cumulative_{int(milestone)}"
        if not self.db.was_alert_sent(alert_key):
            self.db.mark_alert_sent(alert_key)
            self.telegram.send_plain(
                f"💰 Aviso de gasto acumulado: superaste ${milestone:.0f} USD "
                f"en Haiku (total actual: ${cumulative:.2f})."
            )

    def alert_safety_stop(self):
        if self.telegram is None:
            return
        today = self.db.get_today_cost()
        alert_key = f"safety_stop_{self.db.get_today_stats().get('date')}"
        if not self.db.was_alert_sent(alert_key):
            self.db.mark_alert_sent(alert_key)
            self.telegram.send_plain(
                f"🛑 Safety stop: gasto de hoy ${today:.2f} alcanzó el límite "
                f"de ${config.DAILY_SAFETY_STOP_USD}. Pauso el scoring por hoy."
            )

    def alert_credit_exhausted(self, detail: str = ""):
        if self.telegram is None:
            return
        alert_key = f"credit_exhausted_{self.db.get_today_stats().get('date')}"
        if not self.db.was_alert_sent(alert_key):
            self.db.mark_alert_sent(alert_key)
            short = (detail or "")[:200]
            self.telegram.send_plain(
                "⚠️ Parece que se acabó el saldo de Anthropic (o la API key "
                f"falló). El bot no puede scorear. Detalle: {short}"
            )
