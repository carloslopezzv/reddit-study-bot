"""
main.py — Orquestador del bot de oportunidades de Reddit para StudyBuddy.vc.

Flujo:
  1. Chequear pausa y credenciales.
  2. Recolectar posts: /new de cada subreddit semilla + búsqueda cross-sub por
     keyword (en todos los idiomas).
  3. Pre-filtrar barato (sin Haiku).
  4. Scorear con Haiku los que pasan (respetando budget/kill switch).
  5. Mandar a Telegram los que llegan al umbral (SIN generar reply).
  6. Resumen diario.

El bot NO genera replies. Termina su trabajo al notificar la oportunidad.
"""

import sys

import config
from database import Database
from reddit_client import RedditClient
from claude_client import ClaudeScorer, AnthropicCreditError
from telegram_client import TelegramClient
from cost_tracker import CostTracker
import filters


# Detección de idioma (opcional, solo para etiquetar). Degrada con gracia.
try:
    from langdetect import detect as _ld_detect, DetectorFactory
    DetectorFactory.seed = 0

    def detect_language(text: str) -> str:
        text = (text or "").strip()
        if len(text) < 20:
            return "?"
        try:
            return _ld_detect(text)
        except Exception:
            return "?"
except Exception:  # langdetect no instalado
    def detect_language(text: str) -> str:
        return "?"


def _check_env() -> list:
    """Devuelve lista de variables faltantes (vacía si todo OK)."""
    required = {
        "REDDIT_CLIENT_ID": config.REDDIT_CLIENT_ID,
        "REDDIT_CLIENT_SECRET": config.REDDIT_CLIENT_SECRET,
        "ANTHROPIC_API_KEY": config.ANTHROPIC_API_KEY,
        "TELEGRAM_BOT_TOKEN": config.TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": config.TELEGRAM_CHAT_ID,
    }
    return [k for k, v in required.items() if not v]


def collect_candidates(reddit: RedditClient) -> dict:
    """Recolecta posts candidatos. Devuelve dict {post_id: post_dict} deduplicado."""
    candidates = {}

    # 1) /new de cada subreddit semilla
    for sub in config.SEED_SUBREDDITS:
        for post in reddit.get_recent_posts(sub):
            candidates.setdefault(post["id"], post)

    # 2) búsqueda cross-subreddit por keyword (todos los idiomas)
    all_keywords = [
        kw for kws in config.SEARCH_KEYWORDS_BY_LANGUAGE.values() for kw in kws
    ]
    for kw in all_keywords:
        for post in reddit.search_posts(kw):
            candidates.setdefault(post["id"], post)

    return candidates


def process_post(post, db, scorer, telegram, tracker) -> str:
    """Procesa un post. Devuelve un código de resultado para stats/log."""
    # Pre-filtro barato
    passes, reason = filters.prefilter_post(post, db)
    if not passes:
        db.mark_post(post["id"], post["subreddit"], score=None, sent=False)
        return f"prefiltered:{reason}"

    # Budget / kill switch
    ok, why = tracker.can_spend()
    if not ok:
        if why.startswith("safety_stop") or why.startswith("hard_ceiling"):
            tracker.alert_safety_stop()
        return f"budget_stop:{why}"

    # Scoring con Haiku
    result = scorer.score(post)
    tracker.record(result["cost"])
    db.bump_stat("posts_evaluated", 1)

    score = result["score"]
    db.mark_post(post["id"], post["subreddit"], score=score, sent=False)

    if score >= config.TELEGRAM_SCORE_THRESHOLD:
        db.bump_stat("scored_high", 1)
        opp = {
            "kind": "post",
            "score": score,
            "subreddit": post["subreddit"],
            "author": post["author"],
            "permalink": post["permalink"],
            "title": post["title"],
            "body": post["body"],
            "reason": result["reason"],
        }
        if telegram is not None:
            telegram.send_opportunity(opp)
        db.bump_stat("sent_to_telegram", 1)
        db.mark_post(post["id"], post["subreddit"], score=score, sent=True)

        # Anti-spam opcional: marcar autor para no re-notificar otros posts suyos.
        if config.MARK_AUTHOR_ON_SEND:
            db.mark_author_replied(post["author"])

        return f"sent:{score}"

    return f"scored_low:{score}"


def run():
    # Pausa manual
    if config.BOT_PAUSED:
        print("BOT_PAUSED=true → no hago nada.")
        return 0

    missing = _check_env()
    if missing:
        print(f"Faltan variables de entorno: {', '.join(missing)}")
        return 1

    db = Database()
    reddit = RedditClient()
    scorer = ClaudeScorer()
    telegram = TelegramClient()
    tracker = CostTracker(db, telegram=telegram)

    results = {}

    def tally(code):
        results[code] = results.get(code, 0) + 1

    print("Recolectando candidatos...")
    candidates = collect_candidates(reddit)
    print(f"Candidatos únicos: {len(candidates)}")

    credit_error = None
    notifs_this_run = 0

    for post_id, post in candidates.items():
        if db.is_post_seen(post_id):
            tally("already_seen")
            continue
        if notifs_this_run >= config.MAX_TELEGRAM_NOTIFS_PER_RUN:
            tally("max_notifs_reached")
            db.mark_post(post_id, post["subreddit"], score=None, sent=False)
            continue

        try:
            code = process_post(post, db, scorer, telegram, tracker)
        except AnthropicCreditError as e:
            credit_error = str(e)
            break
        tally(code)
        if code.startswith("sent:"):
            notifs_this_run += 1

        # Comments de posts con engagement alto (opcional)
        if config.EVALUATE_COMMENTS and (post.get("score") or 0) >= config.COMMENT_ENGAGEMENT_MIN_SCORE:
            try:
                comments = reddit.get_top_comments(post)
            except Exception as e:
                comments = []
                print(f"[main] error comments: {e}")
            for c in comments:
                if db.is_comment_seen(c["id"]):
                    continue
                cpass, creason = filters.prefilter_comment(c, db)
                if not cpass:
                    db.mark_comment(c["id"], c["post_id"], score=None, sent=False)
                    continue
                ok, why = tracker.can_spend()
                if not ok:
                    if why.startswith(("safety_stop", "hard_ceiling")):
                        tracker.alert_safety_stop()
                    break
                try:
                    cres = scorer.score(c)
                except AnthropicCreditError as e:
                    credit_error = str(e)
                    break
                tracker.record(cres["cost"])
                db.bump_stat("posts_evaluated", 1)
                db.mark_comment(c["id"], c["post_id"], score=cres["score"], sent=False)
                if cres["score"] >= config.TELEGRAM_SCORE_THRESHOLD and notifs_this_run < config.MAX_TELEGRAM_NOTIFS_PER_RUN:
                    db.bump_stat("scored_high", 1)
                    telegram.send_opportunity({
                        "kind": "comment",
                        "score": cres["score"],
                        "subreddit": c["subreddit"],
                        "author": c["author"],
                        "permalink": c["permalink"],
                        "title": "",
                        "body": c["body"],
                        "reason": cres["reason"],
                    })
                    db.bump_stat("sent_to_telegram", 1)
                    db.mark_comment(c["id"], c["post_id"], score=cres["score"], sent=True)
                    notifs_this_run += 1
                    tally("comment_sent")
            if credit_error:
                break

    # Manejo de saldo agotado
    if credit_error:
        tracker.alert_credit_exhausted(credit_error)
        print(f"Saldo Anthropic agotado / error de API: {credit_error}")

    # Resumen
    stats = db.get_today_stats()
    print("=== RESULTADOS DE LA CORRIDA ===")
    for k, v in sorted(results.items()):
        print(f"  {k}: {v}")
    print(f"  costo_corrida: ${tracker.run_cost:.4f}")
    print(f"  costo_hoy: ${db.get_today_cost():.4f}")

    telegram.send_daily_summary(stats)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(run())
