"""
claude_client.py — SOLO scoring con Claude Haiku 4.5. NO genera replies.

Decisión de diseño deliberada: el bot termina su trabajo al mandar la
oportunidad a Telegram. El dueño genera los replies a mano en su chat de
marketing (Opus, Plan Pro). Acá NO se llama a Sonnet ni Opus, y NO se
produce texto de respuesta. Solo: score 0-10 + razón corta.

El system prompt internaliza el criterio del chat de marketing (qué califica,
skip rules de Reddit menos estrictas que YouTube, anti-claims) para que Haiku
puntúe alineado con lo que el dueño respondería.
"""

import json
import re

import anthropic

import config


# ---------------------------------------------------------------------------
# System prompt: criterio de scoring (internaliza el doc de marketing)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
Eres un evaluador de oportunidades de marketing para StudyBuddy.vc. Tu ÚNICO \
trabajo es puntuar de 0 a 10 qué tan buena oportunidad es un post (o comment) \
de Reddit para que el dueño decida si responder manualmente. NO escribes \
respuestas. NO redactas replies. Solo evalúas y das una razón corta.

QUÉ ES STUDYBUDDY.VC (para entender qué problema califica):
Herramienta de estudio con IA, gratuita. Genera preguntas de opción múltiple \
(MCQ) y flashcards a partir del material que sube el usuario (apuntes, PDFs, \
slides). Funciona en muchos idiomas: detecta el idioma del documento y genera \
todo en ese idioma.
Funciones clave:
- MCQ desde el material del usuario.
- Feedback por distractor: cuando fallas, te dice por qué esa opción concreta \
está mal (no solo cuál era la correcta).
- Dificultad adaptativa.
- Selección de temas ponderada: los temas débiles reciben hasta 12.5x más \
prioridad.
- Repetición espaciada ENTRE sesiones (NO dentro de una misma sesión).
- Flashcards autogeneradas y editables, con imágenes, botón "Know It".
- Procesamiento en menos de un minuto (real: 40-100s).

ANTI-CLAIMS (NO puntúes alto si responder bien requeriría una afirmación falsa):
- StudyBuddy NO está "powered by GPT-X".
- No inventes conteos de usuarios ni testimonios.
- La repetición espaciada NO aplica dentro de una sola sesión, solo entre días.
- El procesamiento NO es "30 segundos" (es 40-100s).
Si la única forma de que StudyBuddy encaje sería con un claim falso, baja el score.

CALIFICA ALTO cuando el problema del usuario es del tipo que StudyBuddy resuelve:
- Pide herramienta de práctica MCQ / flashcards desde sus propias notas.
- Se queja de olvidar entre sesiones, de no saber si está aprendiendo, de \
distractores de relleno (Quizlet/Anki), de no encontrar decks para su clase, \
de material denso, de no saber por dónde empezar, de poco tiempo.
- Estudia algo "MCQ-able" (medicina, enfermería, NCLEX/USMLE/MCAT/ENARM \
content review, biología, química conceptual, derecho memorístico, etc.).

REGLAS DE DESCARTE (puntúa BAJO 0-3 automáticamente, SOLO en estos casos — \
Reddit es MENOS conservador que YouTube, así que no descartes por otras razones):
1. Crisis emocional clara o señales de auto-daño. (Score 0-1. Nunca es oportunidad.)
2. Materia no-MCQ-able: escritura creativa, fluidez conversacional de idiomas, \
   artes escénicas, ensayos, programar de verdad (no teoría memorística).
3. El usuario ya tiene un stack completo establecido (ej: UWorld + Anki + \
   Sketchy + Mehlman) Y está en período "dedicated" pre-examen. (Solo entonces.)
4. El post es de un competidor promocionando su propia herramienta.
5. La respuesta correcta sería "habla con un humano" (mentor, terapeuta, asesor).

NO descartes (siguen siendo válidos en Reddit):
- Posts dentro de los últimos 30 días aunque no sean de hoy.
- Threads donde ya recomendaron otras herramientas.
- Subreddits chicos.
- USMLE/NCLEX en fase pre-dedicated (todavía hay valor en content review).

RÚBRICA (0-10):
9-10: Pregunta directa pidiendo herramienta MCQ/flashcards que StudyBuddy \
resuelve perfecto. Ej: "any flashcard apps that aren't Quizlet?".
7-8: Estudiante con problema claro donde StudyBuddy encaja bien. Ej: "I keep \
forgetting", "Quizlet answers feel like filler", queja específica de Anki/Quizlet.
5-6: Borderline. Estudia algo donde StudyBuddy podría encajar pero no es obvio. \
Posts generales de "how to study" en subs grandes.
3-4: Estudio donde StudyBuddy es complemento débil; el reply requeriría ángulo \
creativo. El dueño puede pasar.
1-2: Menciona estudio pero StudyBuddy no encaja. Crisis emocional leve. Materia \
no-MCQ.
0: Irrelevante; pasó por error del filtro.

IDIOMA: el post puede estar en cualquier idioma. Evalúalo igual; el idioma NO \
baja el score (StudyBuddy es multi-idioma).

FORMATO DE SALIDA (OBLIGATORIO): responde EXCLUSIVAMENTE con un objeto JSON \
válido, sin texto antes ni después, sin markdown, con exactamente estas claves:
{"score": <entero 0-10>, "reason": "<máx 20 palabras, en el idioma del post, \
explicando POR QUÉ ese score>", "skip_rule": "<none|crisis|non_mcq|complete_stack|competitor|talk_to_human>"}
La clave "reason" debe ser breve y concreta. NO incluyas ningún reply ni \
sugerencia de texto de respuesta."""


def _build_user_content(item: dict) -> str:
    """Arma el contenido a evaluar. `item` tiene kind, title, body, subreddit."""
    kind = item.get("kind", "post")
    if kind == "comment":
        return (
            f"Tipo: COMMENT de Reddit\n"
            f"Subreddit: r/{item.get('subreddit', '?')}\n"
            f"Texto del comment:\n{item.get('body', '')}"
        )
    return (
        f"Tipo: POST de Reddit\n"
        f"Subreddit: r/{item.get('subreddit', '?')}\n"
        f"Título: {item.get('title', '')}\n"
        f"Body:\n{item.get('body', '') or '(sin body)'}"
    )


# Excepción propia para señalar "se acabó el saldo de Anthropic".
class AnthropicCreditError(Exception):
    pass


_CREDIT_HINTS = ("credit balance", "insufficient", "billing", "quota", "payment")


class ClaudeScorer:
    def __init__(self, api_key: str = None):
        self.client = anthropic.Anthropic(api_key=api_key or config.ANTHROPIC_API_KEY)

    def _system_blocks(self):
        """System prompt, con cache_control si el caching está activado."""
        if config.USE_PROMPT_CACHING:
            return [
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        return SYSTEM_PROMPT

    def score(self, item: dict) -> dict:
        """Scorea un item. Devuelve dict con:
        score (int), reason (str), skip_rule (str), cost (float),
        input_tokens, output_tokens, cache_read_tokens.

        Lanza AnthropicCreditError si la API indica saldo agotado.
        """
        user_content = _build_user_content(item)
        try:
            resp = self.client.messages.create(
                model=config.HAIKU_MODEL,
                max_tokens=150,
                system=self._system_blocks(),
                messages=[{"role": "user", "content": user_content}],
            )
        except anthropic.APIStatusError as e:
            msg = str(getattr(e, "message", "") or e).lower()
            if e.status_code in (400, 402, 403, 429) and any(h in msg for h in _CREDIT_HINTS):
                raise AnthropicCreditError(str(e)) from e
            raise
        except anthropic.AuthenticationError as e:
            # Clave inválida o sin saldo a veces se reporta acá.
            raise AnthropicCreditError(str(e)) from e

        text = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
        parsed = self._parse_json(text)

        usage = resp.usage
        cost = self._compute_cost(usage)

        return {
            "score": parsed["score"],
            "reason": parsed["reason"],
            "skip_rule": parsed.get("skip_rule", "none"),
            "cost": cost,
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "raw": text,
        }

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Parsea el JSON de Haiku de forma robusta (tolera basura alrededor)."""
        cleaned = text.strip()
        # Quitar fences ```json ... ``` si aparecieran.
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError:
            # Buscar el primer bloque {...} dentro del texto.
            m = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not m:
                # Último recurso: score 0 para no romper el flujo.
                return {"score": 0, "reason": "parse_error", "skip_rule": "none"}
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                return {"score": 0, "reason": "parse_error", "skip_rule": "none"}

        # Normalizar score a entero 0-10.
        try:
            score = int(round(float(obj.get("score", 0))))
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(10, score))

        reason = str(obj.get("reason", "")).strip()[:300] or "(sin razón)"
        skip_rule = str(obj.get("skip_rule", "none")).strip() or "none"
        return {"score": score, "reason": reason, "skip_rule": skip_rule}

    @staticmethod
    def _compute_cost(usage) -> float:
        """Costo USD de una llamada a partir del usage de la API."""
        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

        cost = (
            inp / 1_000_000 * config.PRICE_INPUT_PER_MTOK
            + out / 1_000_000 * config.PRICE_OUTPUT_PER_MTOK
            + cache_read / 1_000_000 * config.PRICE_CACHE_READ_PER_MTOK
            + cache_write / 1_000_000 * config.PRICE_CACHE_WRITE_PER_MTOK
        )
        return cost
