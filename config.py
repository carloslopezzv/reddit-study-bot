"""
config.py — Configuración central del bot de oportunidades de Reddit.

Todo lo ajustable vive acá. El dueño puede editar listas/umbrales sin tocar
el resto del código. Las credenciales NUNCA van acá: se leen de variables de
entorno (.env localmente, GitHub Secrets en CI).
"""

import os

# ---------------------------------------------------------------------------
# Credenciales (se leen de entorno; ver .env.example). NO hardcodear acá.
# ---------------------------------------------------------------------------
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get(
    "REDDIT_USER_AGENT", "studybuddy-opportunity-bot:v1.0 (by /u/UNKNOWN)"
)
# Opcionales: solo si algún día se quiere pasar a modo escritura. Para lectura
# (lo que necesitamos) NO hacen falta.
REDDIT_USERNAME = os.environ.get("REDDIT_USERNAME", "")
REDDIT_PASSWORD = os.environ.get("REDDIT_PASSWORD", "")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Pausa manual de emergencia: poner "true" para que el bot no haga nada.
BOT_PAUSED = os.environ.get("BOT_PAUSED", "false").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Modelo Anthropic (SOLO Haiku — verificado contra docs.claude.com)
# ---------------------------------------------------------------------------
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Precios por millón de tokens (USD). Verificados 2026.
PRICE_INPUT_PER_MTOK = 1.00
PRICE_OUTPUT_PER_MTOK = 5.00
PRICE_CACHE_READ_PER_MTOK = 0.10   # lectura de prompt cacheado
PRICE_CACHE_WRITE_PER_MTOK = 1.25  # escritura de cache (5 min)

# Usamos prompt caching sobre el system prompt (rúbrica grande y estable).
# Reduce el costo de input drásticamente cuando se scorean muchos posts seguidos.
USE_PROMPT_CACHING = True


# ---------------------------------------------------------------------------
# Presupuesto y kill switch (Haiku-only => barato)
# ---------------------------------------------------------------------------
DAILY_HARD_CEILING_USD = 5.00   # techo duro: jamás pasar de acá
DAILY_SAFETY_STOP_USD = 3.00    # safety stop: dejar de scorear al llegar acá
CUMULATIVE_ALERT_STEP_USD = 15.00  # alertar a Telegram cada $15 acumulados


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
# Umbral para mandar a Telegram. Arrancamos en 6 a propósito para ver los
# "borderlines" (score 6). Después de 2-3 días el dueño decide si sube a 7.
TELEGRAM_SCORE_THRESHOLD = int(os.environ.get("TELEGRAM_SCORE_THRESHOLD", "6"))


# ---------------------------------------------------------------------------
# Recolección de posts
# ---------------------------------------------------------------------------
# Cuántos posts recientes traer por subreddit (de /new).
POSTS_PER_SUBREDDIT = int(os.environ.get("POSTS_PER_SUBREDDIT", "30"))

# Cuántos resultados traer por cada keyword en la búsqueda cross-subreddit.
SEARCH_RESULTS_PER_KEYWORD = int(os.environ.get("SEARCH_RESULTS_PER_KEYWORD", "15"))

# Ventana de búsqueda para search global ('hour','day','week','month','year','all').
SEARCH_TIME_FILTER = os.environ.get("SEARCH_TIME_FILTER", "week")

# Antigüedad máxima de un post para considerarlo (en días). Reddit es permisivo.
MAX_POST_AGE_DAYS = int(os.environ.get("MAX_POST_AGE_DAYS", "30"))


# ---------------------------------------------------------------------------
# Comments (opcional)
# ---------------------------------------------------------------------------
# Si True, también evalúa los top-N comments de posts con engagement alto.
# Ojo: cada comment evaluado cuesta una llamada extra a Haiku.
EVALUATE_COMMENTS = os.environ.get("EVALUATE_COMMENTS", "false").lower() in (
    "1", "true", "yes",
)
# Un post se considera "engagement alto" (candidato a revisar comments) si su
# score de Reddit supera este número.
COMMENT_ENGAGEMENT_MIN_SCORE = int(os.environ.get("COMMENT_ENGAGEMENT_MIN_SCORE", "20"))
# Cuántos top-comments evaluar como máximo por post.
TOP_COMMENTS_PER_POST = int(os.environ.get("TOP_COMMENTS_PER_POST", "5"))
# Largo mínimo (chars) de un comment para que valga la pena evaluarlo.
MIN_COMMENT_LENGTH = 60


# ---------------------------------------------------------------------------
# Límites de seguridad por corrida (evitan gasto runaway aunque falle el budget)
# ---------------------------------------------------------------------------
MAX_HAIKU_CALLS_PER_RUN = int(os.environ.get("MAX_HAIKU_CALLS_PER_RUN", "400"))
MAX_TELEGRAM_NOTIFS_PER_RUN = int(os.environ.get("MAX_TELEGRAM_NOTIFS_PER_RUN", "40"))


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "reddit_bot.db")


# ---------------------------------------------------------------------------
# Subreddits semilla (ampliable). El bot también descubre subs nuevos vía search.
# ---------------------------------------------------------------------------
SEED_SUBREDDITS = [
    # English (US, UK, AUS, IN)
    "GetStudying", "college", "studytips", "Anki", "Quizlet",
    "medicalschool", "premed", "MCAT", "NCLEX", "USMLE",
    "Step1", "Step2", "APStudents", "SAT", "ACT",
    "GradSchool", "lawschoolprep",
    "nursingstudent", "StudentNurse",
    "EngineeringStudents",
    "JEENEETards", "Indian_Academia",
    "u_of_t", "UofT", "UBC", "UniMelb",
    # Spanish
    "EstudiantesUNAM", "Mexico", "MexicoCity",
    "Spain", "es",
    "Argentina", "Colombia", "Chile",
    "Medicina", "estudiar",
    "ENARM",
    # Portuguese
    "brasil", "estudos", "medicina_BR",
    # German
    "studium", "Universitaet",
    # French
    "etudiants", "EtudiantsFrancais",
    # (Italiano quitado: ver nota en SEARCH_KEYWORDS_BY_LANGUAGE)
    # Indian English/Hindi
    "indianstudents", "GATEtard",
]

# Subreddits "prioritarios": un post acá pasa el pre-filtro aunque no matchee
# keyword (el sub ya es 100% temático de estudio). Mantener chico y curado.
PRIORITY_SUBREDDITS = {
    "getstudying", "studytips", "anki", "quizlet",
    "medicalschool", "premed", "mcat", "nclex", "usmle",
    "step1", "step2", "apstudents", "sat", "act",
    "nursingstudent", "studentnurse", "enarm", "estudiar",
    "estudos", "gatetard",
}


# ---------------------------------------------------------------------------
# Keywords de búsqueda y pre-filtro (multi-idioma). Ampliable.
# ---------------------------------------------------------------------------
SEARCH_KEYWORDS_BY_LANGUAGE = {
    "en": [
        "how to study", "any flashcard app", "what app for studying",
        "anki alternative", "quizlet alternative", "i keep forgetting",
        "I can't memorize", "free study tool", "practice questions for",
        "study tips", "best study app", "study method recommendation",
        "I'm struggling with",
    ],
    "es": [
        "cómo estudiar", "se me olvida todo", "tips de estudio",
        "alguna app para estudiar", "alternativa a quizlet",
        "alguna app gratis", "no puedo memorizar", "técnicas de estudio",
        "preparación examen", "como pasar examen",
    ],
    "pt": [
        "como estudar", "aplicativo para estudar",
        "alternativa ao quizlet", "estou esquecendo tudo",
        "dicas de estudo",
    ],
    "de": [
        "wie lernen", "lern app", "karteikarten app",
        "Quizlet alternative",
    ],
    "fr": [
        "comment étudier", "appli pour réviser",
        "alternative à quizlet",
    ],
    # Italiano quitado: baja penetración de Reddit en Italia y ROI esperado bajo.
    # El bot igual scorea posts en italiano si aparecen (Haiku evalúa cualquier
    # idioma); solo desactivamos el descubrimiento proactivo por keyword.
}

# Set plano de todas las keywords (lowercase) para el pre-filtro de membresía.
# Se computa una sola vez al importar.
ALL_KEYWORDS_LOWER = sorted(
    {
        kw.lower()
        for kws in SEARCH_KEYWORDS_BY_LANGUAGE.values()
        for kw in kws
    }
)

# Marca del propio producto: si ya aparece en el post, lo saltamos (ya lo vieron).
PRODUCT_MENTION_MARKERS = ["studybuddy", "study buddy.vc", "studybuddy.vc"]


# ---------------------------------------------------------------------------
# Anti-spam de autores
# ---------------------------------------------------------------------------
# El bot NO responde (find-only), así que por default NO marca autores como
# "ya respondidos" al notificar (el dueño puede no responder ese post).
# La tabla replied_authors existe igual: el dueño puede poblarla a mano si quiere
# que el bot deje de notificarle posts de un autor.
# Si en la práctica un mismo autor genera demasiadas notifs, poné esto en True
# para que tras la PRIMERA notif de un autor no se notifiquen sus otros posts.
MARK_AUTHOR_ON_SEND = os.environ.get("MARK_AUTHOR_ON_SEND", "false").lower() in (
    "1", "true", "yes",
)
