# Guía de instalación — Bot de oportunidades de Reddit (StudyBuddy.vc)

Esta guía es para alguien **no-técnico**. Seguí los pasos en orden. No hace falta
saber programar. Lo único nuevo respecto al bot de YouTube es el **paso 1 (OAuth
de Reddit)**, así que ese va bien detallado.

> **Recordá:** este bot SOLO encuentra oportunidades y te las manda a Telegram.
> NO escribe respuestas. Vos generás los replies a mano en tu chat de marketing.

---

## Resumen de lo que vas a necesitar (10-20 min)

1. Credenciales de Reddit (client_id + client_secret) — **lo nuevo**
2. Tu API key de Anthropic (la misma que ya usás)
3. Un bot de Telegram **nuevo** (distinto al de YouTube) + tu chat_id
4. Una cuenta de GitHub (gratis)

---

## PASO 1 — Crear la app de Reddit (OAuth) 🆕

Reddit no usa una "API key" simple como otros servicios. Usa OAuth, que suena
complicado pero para solo-lectura son 4 clics.

1. Entrá a **https://www.reddit.com/prefs/apps** (logueado con tu cuenta de Reddit).
2. Bajá hasta el final y hacé clic en **"create another app..."** (o "are you a
   developer? create an app...").
3. Llená el formulario:
   - **name:** `studybuddy-opportunity-bot` (cualquier nombre sirve)
   - Tipo: elegí **"script"** ← importante, no "web app" ni "installed app".
   - **description:** podés dejarlo vacío.
   - **about url:** vacío.
   - **redirect uri:** poné `http://localhost:8080` (no se usa en read-only, pero
     el formulario lo exige).
4. Clic en **"create app"**.
5. Ahora vas a ver la app creada. Anotá estos dos datos:
   - **client_id**: es el texto corto que aparece **debajo del nombre de la app**,
     arriba a la izquierda (debajo de donde dice "personal use script").
   - **client_secret**: aparece en el campo que dice **"secret"**.

   ⚠️ Tratá estos dos valores como contraseñas. No los compartas ni los subas a
   ningún lado público.

6. El **user agent** es un texto identificatorio. Usá exactamente este formato,
   reemplazando `TU_USUARIO` por tu nombre de usuario real de Reddit:
   ```
   studybuddy-opportunity-bot:v1.0 (by /u/TU_USUARIO)
   ```

Eso es todo para Reddit. **No** necesitás tu usuario ni contraseña de Reddit:
el bot solo lee, y la lectura funciona con client_id + client_secret.

---

## PASO 2 — Tu API key de Anthropic

Usá la misma que ya tenés del bot de YouTube. Si necesitás una nueva:
1. Entrá a **https://console.anthropic.com** → API Keys → "Create Key".
2. Copiala (empieza con `sk-ant-...`). Solo se muestra una vez.

> El bot usa **únicamente Claude Haiku 4.5**, que es barato ($1/$5 por millón de
> tokens). El gasto estimado es **$0.20–$0.80 por día**. Igual tiene freno
> automático a **$3/día** (safety stop) y techo duro de **$5/día**.

---

## PASO 3 — Crear un bot de Telegram NUEVO

Creá uno **distinto** al del bot de YouTube, para no mezclar notificaciones.

1. En Telegram, buscá **@BotFather** y abrí el chat.
2. Escribí `/newbot` y seguí las instrucciones (nombre + username que termine en
   `bot`).
3. BotFather te da un **token** (algo como `123456789:AAH...`). Anotalo.
4. Para sacar tu **chat_id**:
   - Buscá **@userinfobot** en Telegram, abrí el chat y mandá cualquier mensaje.
     Te responde con tu `Id` numérico. Ese es tu **chat_id**.
   - Importante: abrí el chat con tu bot nuevo y mandale un "hola" para que el bot
     pueda escribirte (Telegram exige que vos inicies la conversación primero).

---

## PASO 4 — Configurar el `.env` localmente (para probar primero)

Antes de subir nada a GitHub, vamos a probarlo en tu compu.

1. Necesitás Python instalado (3.10 o superior). Verificalo abriendo una terminal
   y escribiendo `python3 --version`. Si no lo tenés, descargalo de
   **https://www.python.org/downloads/**.
2. Descomprimí la carpeta `reddit_agent` que te paso.
3. Abrí una terminal **dentro** de esa carpeta.
4. Instalá las dependencias:
   ```
   pip install -r requirements.txt
   ```
5. Hacé una copia del archivo `.env.example` y llamala `.env`:
   - En Mac/Linux: `cp .env.example .env`
   - En Windows: copiá y pegá el archivo, renombrándolo a `.env`
6. Abrí `.env` con un editor de texto y completá los valores que anotaste:
   ```
   REDDIT_CLIENT_ID=...        (paso 1)
   REDDIT_CLIENT_SECRET=...    (paso 1)
   REDDIT_USER_AGENT=studybuddy-opportunity-bot:v1.0 (by /u/TU_USUARIO)
   ANTHROPIC_API_KEY=sk-ant-...   (paso 2)
   TELEGRAM_BOT_TOKEN=...      (paso 3)
   TELEGRAM_CHAT_ID=...        (paso 3)
   ```
   El resto podés dejarlo como está.

---

## PASO 5 — Probar localmente (¡este paso es clave!)

Antes de automatizar nada, corré el bot a mano para ver qué encuentra:

```
python main.py
```

El bot va a:
- Recolectar posts de los subreddits y búsquedas.
- Filtrarlos y scorearlos con Haiku.
- Mandarte a Telegram las oportunidades con score 6 o más.
- Mostrarte en la terminal un resumen (cuántos evaluó, cuántos mandó, cuánto gastó).

**Qué revisar:**
- ¿Llegan notificaciones a Telegram? (Target: 15–30 por día, pero en una sola
  corrida verás menos.)
- ¿Las oportunidades son posteables? ¿Son del tipo que vos responderías?
- ¿Hay falsos positivos (posts que no encajan) o falsos negativos (buenos que no
  llegaron)?

Corré `python main.py` **2 o 3 veces** a lo largo de un día o dos para juntar
suficientes ejemplos. Como la base de datos recuerda lo ya visto, cada corrida
solo procesa posts nuevos.

> **Ajuste del umbral:** arranca en **6** a propósito, para que veas los
> "borderlines". Si te llegan demasiados posts flojos, subí el umbral a 7
> editando `TELEGRAM_SCORE_THRESHOLD=7` en el `.env`. Si querés más volumen,
> dejalo en 6.

**Solo cuando estés conforme con la calidad**, pasá al paso 6.

---

## PASO 6 — Subir a GitHub Actions (automatización)

Esto hace que el bot corra solo cada 6 horas, sin tu compu prendida.

1. Creá una cuenta en **https://github.com** si no tenés.
2. Creá un repositorio **nuevo y privado** (botón "New", marcá "Private").
3. Subí los archivos de la carpeta `reddit_agent` al repo:
   - La forma más fácil sin terminal: en la página del repo, "Add file" →
     "Upload files", y arrastrá todos los archivos **menos** `.env` y cualquier
     archivo `.db`. (El `.gitignore` ya los excluye, pero por las dudas no los
     subas.)
   - Asegurate de subir también la carpeta `.github/workflows/run.yml` (mantené
     esa estructura de carpetas).
4. Cargá los **Secrets** (las credenciales, de forma segura):
   - En el repo: **Settings → Secrets and variables → Actions → New repository
     secret**.
   - Creá uno por cada variable (mismo nombre que en el `.env`):
     - `REDDIT_CLIENT_ID`
     - `REDDIT_CLIENT_SECRET`
     - `REDDIT_USER_AGENT`
     - `ANTHROPIC_API_KEY`
     - `TELEGRAM_BOT_TOKEN`
     - `TELEGRAM_CHAT_ID`
     - (opcional) `TELEGRAM_SCORE_THRESHOLD`, `BOT_PAUSED`, `EVALUATE_COMMENTS`

---

## PASO 7 — Primera corrida automática + verificación

1. En el repo, andá a la pestaña **Actions**.
2. Si te pide habilitar workflows, aceptá.
3. Elegí el workflow **"reddit-opportunity-bot"** en la izquierda.
4. Clic en **"Run workflow"** (botón a la derecha) para dispararlo a mano la
   primera vez (sin esperar al horario).
5. Esperá 1–3 minutos. Hacé clic en la corrida para ver los logs.
6. Verificá que:
   - El log termina sin error y muestra el resumen.
   - Te llegaron las notificaciones a Telegram (y el "Daily summary").

A partir de ahí corre solo: **06:00, 12:00, 18:00 y 00:00 UTC** todos los días.

---

## Controles útiles del día a día

- **Pausar el bot sin borrar nada:** en Settings → Secrets, poné el secret
  `BOT_PAUSED` en `true`. Para reactivar, ponelo en `false` (o borralo).
- **Cambiar el umbral de score:** editá el secret `TELEGRAM_SCORE_THRESHOLD`
  (6 = más volumen con borderlines; 7 = solo lo claro).
- **Evaluar también comentarios** (cuesta un poco más de Haiku): poné
  `EVALUATE_COMMENTS=true`.
- **Agregar subreddits o keywords:** editá `config.py` (listas `SEED_SUBREDDITS`,
  `SEARCH_KEYWORDS_BY_LANGUAGE`, `PRIORITY_SUBREDDITS`) y volvé a subir el archivo.

## Alertas automáticas que vas a recibir en Telegram

- 🛑 Cuando el gasto del día llega al safety stop ($3) y el bot pausa el scoring.
- ⚠️ Cuando parece que se acabó el saldo de Anthropic o falla la API key.
- 💰 Cada vez que el gasto **acumulado** cruza otro múltiplo de $15.
- 📊 Un resumen diario al final de cada corrida.

## Si algo falla

- **No llegan notificaciones:** confirmá que le mandaste "hola" a tu bot de
  Telegram primero, y que el `TELEGRAM_CHAT_ID` es el número correcto.
- **Error de Reddit "401" o "403":** revisá `REDDIT_CLIENT_ID` /
  `REDDIT_CLIENT_SECRET` (que no tengan espacios) y que la app sea tipo "script".
- **Error de Anthropic sobre "credit balance":** recargá saldo en la consola de
  Anthropic.
- **El workflow no aparece en Actions:** confirmá que subiste el archivo en la
  ruta exacta `.github/workflows/run.yml`.

---

### Nota técnica sobre la base de datos en GitHub Actions

El bot guarda lo que ya vio en un archivo `reddit_bot.db`. En GitHub Actions ese
archivo se conserva entre corridas usando la **caché de Actions** (ya configurada
en `run.yml`). Si GitHub alguna vez borra esa caché (pasa raramente, tras semanas
de inactividad), el bot podría re-evaluar algunos posts una vez; no es grave, solo
gasta unos centavos extra de Haiku esa corrida.
