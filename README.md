# Reddit Opportunity Bot — StudyBuddy.vc (find-only)

Bot que busca en Reddit (en cualquier idioma) posts donde estudiantes piden
herramientas de estudio, los scorea con **Claude Haiku 4.5** según el criterio
del chat de marketing, y manda los que pasan el umbral a **Telegram**.

**El bot NO genera replies.** Termina su trabajo al notificar la oportunidad.
El dueño escribe las respuestas a mano en su chat de marketing (Opus, Plan Pro).
Esto baja el costo drásticamente y mantiene la máxima calidad de reply.

## Cómo empezar

Leé **`SETUP_GUIDE.md`** — guía paso a paso para no-técnicos (incluye el OAuth de
Reddit, que es lo más nuevo). Para probar: completá `.env` (ver `.env.example`) y
corré `python main.py`.

## Arquitectura

```
reddit_agent/
├── config.py              # subreddits, keywords, límites, budget, anti-spam
├── reddit_client.py       # wrapper de Reddit (PRAW), solo lectura (OAuth de app)
├── claude_client.py       # SOLO Haiku scoring (sin generación de replies)
├── filters.py             # pre-filtros baratos antes de Haiku
├── database.py            # SQLite (cache/dedup, anti-spam, stats, alertas)
├── cost_tracker.py        # tracking de gasto + kill switch + alertas
├── telegram_client.py     # notifs (2 mensajes: contexto + texto copiable)
├── main.py                # orquestador
├── test_bot.py            # tests con mocks (no toca APIs reales)
├── requirements.txt
├── .env.example
├── .gitignore
├── SETUP_GUIDE.md
└── .github/workflows/run.yml   # cron cada 6h + run manual
```

## Flujo

1. Trae posts recientes (`/new`) de cada subreddit semilla.
2. Busca posts cross-subreddit por keyword en todos los idiomas (descubre subs).
3. Pre-filtra barato (sin Haiku): viejos, removidos, downvoteados, sin keyword,
   ya mencionan SB, autor ya respondido.
4. Scorea con Haiku 1–10 los que pasan (respetando budget/kill switch).
5. Manda a Telegram los de score ≥ umbral (default **6**, configurable).
6. Marca todo en SQLite para no reprocesar. Resumen diario al final.

## Decisiones clave (del spec)

- **Modelo único:** `claude-haiku-4-5-20251001`. Nunca Sonnet ni Opus.
  Precios verificados: $1/MTok input, $5/MTok output ($0.10/MTok cache read).
- **Prompt caching** activado sobre el system prompt (rúbrica grande y estable),
  para abaratar el input cuando se scorean muchos posts seguidos.
- **Umbral inicial 6** a propósito, para ver los borderlines. Subir a 7 después.
- **Skip rules menos estrictas que YouTube**: Haiku solo baja a 0–3 por crisis
  emocional, materia no-MCQ, stack completo en dedicated, competidor, o
  "talk to a human". No descarta por posts viejos (dentro de 30d), threads con
  otras tools, ni subs chicos.
- **Anti-claims** en el system prompt: Haiku no puntúa alto si responder bien
  exigiría un claim falso (GPT-X, "30 segundos", spaced repetition intra-sesión).
- **Presupuesto:** safety stop $3/día, techo duro $5/día, alerta acumulada cada
  $15, alerta si se agota el saldo de Anthropic.
- **Comments:** opcional (`EVALUATE_COMMENTS=true`), solo top-N de posts con
  engagement alto.

## Tests

```
python test_bot.py
```

Cubre imports, pre-filtros (incl. multi-idioma ES/PT/DE/FR), dedup de la DB,
kill switch, cálculo de costo, parseo del JSON de Haiku y formato de Telegram
(link clickeable + escape correcto de MarkdownV2). 44 checks, todos en verde.
