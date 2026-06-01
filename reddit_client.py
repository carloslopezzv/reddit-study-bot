"""
reddit_client.py — Wrapper de la API de Reddit vía PRAW, en modo SOLO LECTURA.

Para lo que necesitamos (leer posts/comments) basta con OAuth de aplicación
(application-only): client_id + client_secret + user_agent. No hace falta
username/password. PRAW maneja el rate limiting solo.

Normaliza los objetos de PRAW a dicts simples para que el resto del bot no
dependa de PRAW.
"""

import praw
import prawcore

import config


def _full_url(permalink: str) -> str:
    """Construye una URL absoluta de Reddit de forma robusta.

    Según la versión de PRAW, `permalink` puede venir como:
    - path relativo con barra inicial:  "/r/sub/comments/.../"   (lo habitual)
    - path relativo sin barra inicial:  "r/sub/comments/.../"
    - URL ya absoluta:                  "https://www.reddit.com/r/sub/..."
    Este helper devuelve siempre una URL válida sin duplicar el dominio.
    """
    p = (permalink or "").strip()
    if not p:
        return "https://www.reddit.com"
    if p.startswith("http://") or p.startswith("https://"):
        return p
    if not p.startswith("/"):
        p = "/" + p
    return f"https://www.reddit.com{p}"


def _post_to_dict(submission) -> dict:
    author = getattr(submission, "author", None)
    author_name = str(author) if author else "[deleted]"
    return {
        "kind": "post",
        "id": submission.id,
        "subreddit": str(submission.subreddit.display_name),
        "author": author_name,
        "title": submission.title or "",
        "body": submission.selftext or "",
        "score": int(getattr(submission, "score", 0) or 0),
        "num_comments": int(getattr(submission, "num_comments", 0) or 0),
        "created_utc": float(getattr(submission, "created_utc", 0) or 0),
        "permalink": _full_url(getattr(submission, "permalink", "")),
        "_submission": submission,  # referencia interna (para traer comments)
    }


def _comment_to_dict(comment, post_id, subreddit) -> dict:
    author = getattr(comment, "author", None)
    author_name = str(author) if author else "[deleted]"
    return {
        "kind": "comment",
        "id": comment.id,
        "post_id": post_id,
        "subreddit": subreddit,
        "author": author_name,
        "title": "",
        "body": comment.body or "",
        "score": int(getattr(comment, "score", 0) or 0),
        "created_utc": float(getattr(comment, "created_utc", 0) or 0),
        "permalink": _full_url(getattr(comment, "permalink", "")),
    }


class RedditClient:
    def __init__(self):
        self.reddit = praw.Reddit(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            user_agent=config.REDDIT_USER_AGENT,
            check_for_async=False,
        )
        # Forzar read-only explícitamente.
        self.reddit.read_only = True

    # -- posts recientes por subreddit -------------------------------------
    def get_recent_posts(self, subreddit_name: str, limit: int = None) -> list:
        limit = limit or config.POSTS_PER_SUBREDDIT
        out = []
        try:
            sub = self.reddit.subreddit(subreddit_name)
            for submission in sub.new(limit=limit):
                out.append(_post_to_dict(submission))
        except prawcore.exceptions.Redirect:
            print(f"[reddit] subreddit no existe: r/{subreddit_name}")
        except prawcore.exceptions.NotFound:
            print(f"[reddit] not found: r/{subreddit_name}")
        except prawcore.exceptions.Forbidden:
            print(f"[reddit] privado/baneado: r/{subreddit_name}")
        except Exception as e:
            print(f"[reddit] error en r/{subreddit_name}: {e}")
        return out

    # -- búsqueda cross-subreddit (descubre subs nuevos) -------------------
    def search_posts(self, keyword: str, limit: int = None,
                     time_filter: str = None) -> list:
        limit = limit or config.SEARCH_RESULTS_PER_KEYWORD
        time_filter = time_filter or config.SEARCH_TIME_FILTER
        out = []
        try:
            allsub = self.reddit.subreddit("all")
            for submission in allsub.search(
                keyword, sort="new", time_filter=time_filter, limit=limit
            ):
                out.append(_post_to_dict(submission))
        except prawcore.exceptions.Forbidden:
            print(f"[reddit] búsqueda prohibida para: {keyword!r}")
        except Exception as e:
            print(f"[reddit] error en search {keyword!r}: {e}")
        return out

    # -- top comments de un post -------------------------------------------
    def get_top_comments(self, post_dict: dict, limit: int = None) -> list:
        limit = limit or config.TOP_COMMENTS_PER_POST
        out = []
        submission = post_dict.get("_submission")
        if submission is None:
            return out
        try:
            submission.comment_sort = "top"
            submission.comments.replace_more(limit=0)  # no expandir "load more"
            for comment in submission.comments[:limit]:
                out.append(
                    _comment_to_dict(comment, post_dict["id"], post_dict["subreddit"])
                )
        except Exception as e:
            print(f"[reddit] error trayendo comments de {post_dict.get('id')}: {e}")
        return out

    def verify_credentials(self) -> bool:
        """Chequeo simple de que las credenciales funcionan (read-only)."""
        try:
            # Una llamada liviana cualquiera.
            _ = self.reddit.subreddit("announcements").id
            return True
        except Exception as e:
            print(f"[reddit] credenciales inválidas: {e}")
            return False
