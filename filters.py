"""
filters.py — Pre-filtros baratos que corren ANTES de gastar Haiku.

Objetivo: descartar obvios no-fits sin pagar una llamada al modelo.
Cada función devuelve (passes: bool, reason: str). `reason` sirve para
debugging/stats cuando un item es rechazado.

Reglas (del spec, menos estrictas que el bot de YouTube):
- Post no más viejo de MAX_POST_AGE_DAYS.
- No [Removed] / [Deleted].
- No score negativo (downvoted = mala señal).
- No mencionar ya "studybuddy".
- Autor no marcado como ya respondido (anti-spam).
- Debe contener al menos un keyword (cualquier idioma) O estar en sub prioritario.
"""

import time

import config


# Marcadores típicos de contenido removido/borrado en Reddit.
_REMOVED_MARKERS = (
    "[removed]", "[deleted]", "[borrado]", "[eliminado]",
)


def _text_of_post(post: dict) -> str:
    """Concatena título + body en minúsculas para chequeos de membresía."""
    return f"{post.get('title', '')} {post.get('body', '')}".lower()


def is_too_old(created_utc: float, max_age_days: int = None) -> bool:
    max_age_days = max_age_days if max_age_days is not None else config.MAX_POST_AGE_DAYS
    age_seconds = time.time() - float(created_utc or 0)
    return age_seconds > max_age_days * 86400


def is_removed_or_deleted(post: dict) -> bool:
    title = (post.get("title") or "").strip().lower()
    body = (post.get("body") or "").strip().lower()
    if body in _REMOVED_MARKERS or title in _REMOVED_MARKERS:
        return True
    # Autor borrado deja "[deleted]" como nombre.
    if (post.get("author") or "").strip().lower() in ("[deleted]", ""):
        # Autor vacío no siempre implica removido (algunos posts), pero sin
        # autor no podemos hacer anti-spam, así que lo tratamos como borrado.
        if (post.get("author") or "").strip().lower() == "[deleted]":
            return True
    return False


def mentions_product(post: dict) -> bool:
    text = _text_of_post(post)
    return any(marker in text for marker in config.PRODUCT_MENTION_MARKERS)


def matches_any_keyword(post: dict) -> bool:
    text = _text_of_post(post)
    return any(kw in text for kw in config.ALL_KEYWORDS_LOWER)


def is_priority_subreddit(subreddit: str) -> bool:
    return (subreddit or "").lower() in config.PRIORITY_SUBREDDITS


def prefilter_post(post: dict, db) -> tuple[bool, str]:
    """Devuelve (passes, reason). Si passes=False, NO gastar Haiku.

    `db` es una instancia de Database (para chequear autor ya respondido).
    `post` es un dict con: id, subreddit, author, title, body, score,
    created_utc.
    """
    # 1. Removido / borrado
    if is_removed_or_deleted(post):
        return False, "removed_or_deleted"

    # 2. Demasiado viejo
    if is_too_old(post.get("created_utc")):
        return False, "too_old"

    # 3. Score negativo (downvoted)
    if (post.get("score") or 0) < 0:
        return False, "negative_score"

    # 4. Ya menciona el producto
    if mentions_product(post):
        return False, "already_mentions_product"

    # 5. Autor ya respondido (anti-spam)
    if db is not None and db.is_author_replied(post.get("author")):
        return False, "author_already_replied"

    # 6. Debe matchear keyword O estar en sub prioritario
    if not (matches_any_keyword(post) or is_priority_subreddit(post.get("subreddit"))):
        return False, "no_keyword_no_priority_sub"

    return True, "passed"


def prefilter_comment(comment: dict, db) -> tuple[bool, str]:
    """Pre-filtro para comments (cuando EVALUATE_COMMENTS=True).

    `comment` es un dict con: id, post_id, author, body, score, created_utc.
    """
    body = (comment.get("body") or "").strip()
    low = body.lower()

    if low in _REMOVED_MARKERS:
        return False, "removed_or_deleted"
    if (comment.get("author") or "").strip().lower() == "[deleted]":
        return False, "deleted_author"
    if len(body) < config.MIN_COMMENT_LENGTH:
        return False, "too_short"
    if is_too_old(comment.get("created_utc")):
        return False, "too_old"
    if (comment.get("score") or 0) < 0:
        return False, "negative_score"
    if any(m in low for m in config.PRODUCT_MENTION_MARKERS):
        return False, "already_mentions_product"
    if db is not None and db.is_author_replied(comment.get("author")):
        return False, "author_already_replied"
    # Comment debe matchear al menos un keyword (no tenemos sub prioritario acá).
    if not any(kw in low for kw in config.ALL_KEYWORDS_LOWER):
        return False, "no_keyword"

    return True, "passed"
