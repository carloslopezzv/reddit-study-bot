"""
test_bot.py — Tests rápidos con mocks. NO hace llamadas reales a Reddit,
Anthropic ni Telegram. Corre con: python test_bot.py

Cubre lo que pide el spec:
- imports limpios
- pre-filtro (thanks-only, ya menciona SB, posts viejos, negativos, keyword)
- multi-idioma (ES/PT/etc.)
- parseo de scoring de Haiku + cálculo de costo (mock de usage)
- formato de mensajes de Telegram (link clickeable, escape correcto)
- cost tracker incrementa y frena (kill switch)
- database cache (no reprocesa)
"""

import os
import sys
import time
import tempfile

# Env mínimo para que los módulos no se quejen al instanciar en otros tests.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import config
import filters
from database import Database
from cost_tracker import CostTracker
from claude_client import ClaudeScorer
import telegram_client as tg


PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ FAIL: {name}")


# ---------------------------------------------------------------------------
def fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path), path


# ---------------------------------------------------------------------------
def test_prefilter():
    print("\n[test] pre-filtros")
    db, path = fresh_db()
    now = time.time()

    # Post válido (keyword EN, reciente, score positivo)
    good = {
        "id": "p1", "subreddit": "college", "author": "alice",
        "title": "any flashcard app that isn't quizlet?",
        "body": "looking for something free", "score": 5, "created_utc": now,
    }
    ok, reason = filters.prefilter_post(good, db)
    check("post bueno pasa", ok and reason == "passed")

    # Thanks-only (sin keyword, sub no prioritario)
    thanks = {
        "id": "p2", "subreddit": "AskReddit", "author": "bob",
        "title": "thanks everyone", "body": "ty so much", "score": 3,
        "created_utc": now,
    }
    ok, reason = filters.prefilter_post(thanks, db)
    check("thanks-only sin keyword es rechazado", (not ok) and reason == "no_keyword_no_priority_sub")

    # Ya menciona el producto
    mentions = {
        "id": "p3", "subreddit": "college", "author": "carol",
        "title": "how to study with studybuddy.vc", "body": "", "score": 2,
        "created_utc": now,
    }
    ok, reason = filters.prefilter_post(mentions, db)
    check("post que ya menciona SB es rechazado", (not ok) and reason == "already_mentions_product")

    # Post viejo (40 días)
    old = {
        "id": "p4", "subreddit": "college", "author": "dave",
        "title": "how to study for finals", "body": "", "score": 5,
        "created_utc": now - 40 * 86400,
    }
    ok, reason = filters.prefilter_post(old, db)
    check("post viejo (>30d) es rechazado", (not ok) and reason == "too_old")

    # Score negativo
    neg = {
        "id": "p5", "subreddit": "college", "author": "eve",
        "title": "how to study better", "body": "", "score": -3,
        "created_utc": now,
    }
    ok, reason = filters.prefilter_post(neg, db)
    check("post con score negativo es rechazado", (not ok) and reason == "negative_score")

    # Removido
    removed = {
        "id": "p6", "subreddit": "college", "author": "frank",
        "title": "how to study", "body": "[removed]", "score": 1,
        "created_utc": now,
    }
    ok, reason = filters.prefilter_post(removed, db)
    check("post [removed] es rechazado", (not ok) and reason == "removed_or_deleted")

    # Autor ya respondido
    db.mark_author_replied("grace")
    replied = {
        "id": "p7", "subreddit": "college", "author": "grace",
        "title": "any study app recommendation", "body": "", "score": 4,
        "created_utc": now,
    }
    ok, reason = filters.prefilter_post(replied, db)
    check("autor ya respondido es rechazado", (not ok) and reason == "author_already_replied")

    # Sub prioritario sin keyword igual pasa
    priosub = {
        "id": "p8", "subreddit": "NCLEX", "author": "henry",
        "title": "feeling overwhelmed by content", "body": "", "score": 2,
        "created_utc": now,
    }
    ok, reason = filters.prefilter_post(priosub, db)
    check("sub prioritario sin keyword igual pasa", ok and reason == "passed")

    db.close()
    os.remove(path)


def test_multilang():
    print("\n[test] multi-idioma (keywords ES/PT/DE/FR)")
    db, path = fresh_db()
    now = time.time()

    cases = [
        ("es", "EstudiantesUNAM", "alguien sabe alguna app para estudiar gratis?"),
        ("pt", "brasil", "qual o melhor aplicativo para estudar medicina"),
        ("de", "studium", "welche karteikarten app benutzt ihr"),
        ("fr", "etudiants", "une appli pour réviser le bac?"),
        ("es2", "Argentina", "se me olvida todo lo que estudio, ayuda"),
    ]
    for i, (lang, sub, title) in enumerate(cases):
        post = {
            "id": f"ml{i}", "subreddit": sub, "author": f"user{i}",
            "title": title, "body": "", "score": 3, "created_utc": now,
        }
        ok, reason = filters.prefilter_post(post, db)
        check(f"keyword {lang} matchea ({title[:30]}...)", ok and reason == "passed")

    db.close()
    os.remove(path)


def test_database_cache():
    print("\n[test] database cache / dedup")
    db, path = fresh_db()

    check("post nuevo no visto", not db.is_post_seen("x1"))
    db.mark_post("x1", "college", score=7, sent=True)
    check("post marcado queda visto", db.is_post_seen("x1"))

    db.mark_comment("c1", "x1", score=8, sent=False)
    check("comment marcado queda visto", db.is_comment_seen("c1"))

    db.mark_author_replied("Zoe")
    check("autor marcado (case-insensitive)", db.is_author_replied("zoe"))

    db.close()
    # Reabrir: el estado debe persistir (simula corrida siguiente en CI)
    db2 = Database(path)
    check("estado persiste tras reabrir DB", db2.is_post_seen("x1"))
    db2.close()
    os.remove(path)


def test_cost_tracker():
    print("\n[test] cost tracker + kill switch")
    db, path = fresh_db()
    tracker = CostTracker(db, telegram=None)

    ok, _ = tracker.can_spend()
    check("puede gastar al inicio", ok)

    tracker.record(0.50)
    tracker.record(0.50)
    check("costo de hoy acumula", abs(db.get_today_cost() - 1.0) < 1e-9)
    check("run_cost acumula", abs(tracker.run_cost - 1.0) < 1e-9)
    check("run_calls cuenta", tracker.run_calls == 2)

    # Empujar por encima del safety stop ($3)
    tracker.record(2.60)  # total 3.60 > 3.0
    ok, why = tracker.can_spend()
    check("kill switch frena en safety stop", (not ok) and why.startswith("safety_stop"))

    db.close()
    os.remove(path)


def test_cost_computation():
    print("\n[test] cálculo de costo desde usage (mock)")

    class FakeUsage:
        input_tokens = 1_000_000
        output_tokens = 1_000_000
        cache_read_input_tokens = 0
        cache_creation_input_tokens = 0

    cost = ClaudeScorer._compute_cost(FakeUsage())
    # 1M input ($1) + 1M output ($5) = $6
    check("costo 1M+1M = $6", abs(cost - 6.0) < 1e-6)

    class FakeUsage2:
        input_tokens = 0
        output_tokens = 0
        cache_read_input_tokens = 1_000_000
        cache_creation_input_tokens = 0

    cost2 = ClaudeScorer._compute_cost(FakeUsage2())
    check("cache read 1M = $0.10", abs(cost2 - 0.10) < 1e-6)


def test_json_parsing():
    print("\n[test] parseo robusto del JSON de Haiku")
    p = ClaudeScorer._parse_json

    r = p('{"score": 8, "reason": "pide flashcards", "skip_rule": "none"}')
    check("JSON limpio parsea", r["score"] == 8 and r["skip_rule"] == "none")

    r = p('```json\n{"score": 6, "reason": "borderline"}\n```')
    check("JSON con fences parsea", r["score"] == 6)

    r = p('claro, aquí: {"score": 9, "reason": "x"} listo')
    check("JSON embebido en texto parsea", r["score"] == 9)

    r = p('{"score": 15, "reason": "x"}')
    check("score fuera de rango se clampa a 10", r["score"] == 10)

    r = p("no es json")
    check("texto no-JSON no rompe (score 0)", r["score"] == 0)


def test_telegram_format():
    print("\n[test] formato de mensajes de Telegram")

    # Escape de texto normal
    esc = tg.escape_md_v2("AP Chem (first-year) — help! cost is $5.50")
    check("escapa parentesis", "\\(" in esc and "\\)" in esc)
    check("escapa guion y punto", "\\-" in esc and "\\." in esc and "\\!" in esc)

    # Escape de URL: solo ')' y '\'
    url = "https://www.reddit.com/r/college/comments/abc_def/title_here/"
    esc_url = tg.escape_md_v2_url(url)
    check("URL con underscore NO se escapa (válido en link)", "_" in esc_url and "\\_" not in esc_url)
    url2 = "https://x.com/path(weird)"
    check("URL con parentesis escapa el cierre", "\\)" in tg.escape_md_v2_url(url2))

    # Truncado
    check("truncate corta y agrega elipsis", tg.truncate("a" * 100, 10).endswith("…"))
    check("truncate no toca texto corto", tg.truncate("hola", 10) == "hola")

    # send_opportunity arma 2 mensajes (mock de _send)
    sent = []

    class FakeTG(tg.TelegramClient):
        def __init__(self):
            self.token = "t"
            self.chat_id = "c"
        def _send(self, text, parse_mode=None):
            sent.append((parse_mode, text))
            return True

    client = FakeTG()
    client.send_opportunity({
        "kind": "post", "score": 8, "subreddit": "medicalschool",
        "author": "struggling_student", "permalink": "https://www.reddit.com/r/x/comments/1/t/",
        "title": 'Anyone else completely lost on Step 1?',
        "body": "Studying for Step 1, no clear strategy. " * 5,
        "reason": "Studying for Step 1, mentions struggling",
    })
    check("envía 2 mensajes", len(sent) == 2)
    check("mensaje 1 es MarkdownV2", sent[0][0] == "MarkdownV2")
    check("mensaje 2 es texto plano (sin parse_mode)", sent[1][0] is None)
    check("mensaje 1 tiene link clickeable", "](https://www.reddit.com/r/x/comments/1/t/)" in sent[0][1])
    check("mensaje 1 incluye Why", "Why" in sent[0][1])
    check("mensaje 2 contiene el título crudo", "Anyone else completely lost on Step 1?" in sent[1][1])

    # El mensaje plano NO debe contener un reply generado (find-only)
    check("ningún mensaje contiene 'reply' generado", all("studybuddy.vc" not in t.lower() for _, t in sent))


def main():
    print("=" * 60)
    print("SUITE DE TESTS — Reddit Opportunity Bot (find-only)")
    print("=" * 60)
    test_prefilter()
    test_multilang()
    test_database_cache()
    test_cost_tracker()
    test_cost_computation()
    test_json_parsing()
    test_telegram_format()

    print("\n" + "=" * 60)
    print(f"RESULTADO: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
