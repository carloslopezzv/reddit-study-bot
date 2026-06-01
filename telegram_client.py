"""
telegram_client.py — Notificaciones a Telegram.

Formato por oportunidad = DOS mensajes:
  1) Contexto (MarkdownV2): score, subreddit, autor, link clickeable, título,
     body truncado, y la razón de Haiku.
  2) Texto plano (sin parse_mode): título + body completo, para copiar de un
     toque y pegar en el chat de marketing.

IMPORTANTE: el bot NO genera replies. Estos mensajes NO incluyen ningún
borrador de respuesta. Solo la oportunidad cruda para que el dueño decida.
"""

import requests

import config


# Caracteres que MarkdownV2 obliga a escapar en texto normal.
_MD2_SPECIALS = r"_*[]()~`>#+-=|{}.!"


def escape_md_v2(text: str) -> str:
    """Escapa texto para usarlo como contenido en MarkdownV2."""
    if text is None:
        return ""
    out = []
    for ch in str(text):
        if ch in _MD2_SPECIALS:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def escape_md_v2_url(url: str) -> str:
    """Escapa una URL para usarla dentro de los paréntesis de un link MarkdownV2.
    Dentro de (...) solo hay que escapar ')' y '\\'."""
    if not url:
        return ""
    return url.replace("\\", "\\\\").replace(")", "\\)")


def truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class TelegramClient:
    def __init__(self, token: str = None, chat_id: str = None, session=None):
        self.token = token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        self.session = session or requests.Session()

    @property
    def _base(self):
        return f"https://api.telegram.org/bot{self.token}/sendMessage"

    def _send(self, text: str, parse_mode: str = None) -> bool:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            r = self.session.post(self._base, json=payload, timeout=20)
            data = r.json()
            if not data.get("ok"):
                # Log a stdout; en CI queda en los logs del workflow.
                print(f"[telegram] error: {data}")
                return False
            return True
        except Exception as e:  # red, timeout, etc.
            print(f"[telegram] excepción al enviar: {e}")
            return False

    # -- API pública --------------------------------------------------------
    def send_plain(self, text: str) -> bool:
        """Mensaje sin formato (no parse_mode => no hay que escapar nada)."""
        return self._send(text)

    def send_markdown_v2(self, text: str) -> bool:
        return self._send(text, parse_mode="MarkdownV2")

    def send_opportunity(self, opp: dict) -> bool:
        """Manda los DOS mensajes de una oportunidad.

        `opp` espera: score, subreddit, author, permalink, title, body, reason.
        Devuelve True si el primer mensaje (contexto) se envió OK.
        """
        score = opp.get("score", "?")
        subreddit = opp.get("subreddit", "?")
        author = opp.get("author", "?")
        permalink = opp.get("permalink", "")
        title = opp.get("title", "") or "(sin título)"
        body = opp.get("body", "") or ""
        reason = opp.get("reason", "")
        kind = opp.get("kind", "post")

        # ---- Mensaje 1: contexto (MarkdownV2) ----
        body_trunc = truncate(body, 800)
        emoji = "🎯" if kind == "post" else "💬"
        link_text = "Open post" if kind == "post" else "Open comment"

        msg1 = (
            f"{emoji} *Reddit Opportunity* \\(Score: {escape_md_v2(str(score))}/10\\)\n"
            f"\n"
            f"📍 r/{escape_md_v2(subreddit)}\n"
            f"👤 u/{escape_md_v2(author)}\n"
            f"🔗 [{escape_md_v2(link_text)}]({escape_md_v2_url(permalink)})\n"
            f"\n"
            f"💬 *Title:* {escape_md_v2(truncate(title, 300))}\n"
            f"📝 *Body:* {escape_md_v2(body_trunc) if body_trunc else escape_md_v2('(sin body)')}\n"
            f"\n"
            f"_Why:_ {escape_md_v2(reason)}"
        )
        ok1 = self.send_markdown_v2(msg1)

        # ---- Mensaje 2: texto plano copiable ----
        msg2 = f"{title}\n\n{body}".strip()
        msg2 = truncate(msg2, 4000)  # límite de Telegram ~4096
        self.send_plain(msg2)

        return ok1

    def send_daily_summary(self, stats: dict) -> bool:
        """Resumen diario al final de la corrida."""
        msg = (
            "📊 Daily summary StudyBuddy Reddit bot\n"
            f"Fecha: {stats.get('date', '?')}\n"
            f"Posts evaluados (Haiku): {stats.get('posts_evaluated', 0)}\n"
            f"Scoreados alto (>= umbral): {stats.get('scored_high', 0)}\n"
            f"Enviados a Telegram: {stats.get('sent_to_telegram', 0)}\n"
            f"Costo Haiku hoy: ${stats.get('haiku_cost', 0.0):.4f}"
        )
        return self.send_plain(msg)
