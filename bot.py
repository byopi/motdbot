import os
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional
import pytz
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID_ENV = os.environ.get("CHANNEL_ID")
CONFIG_FILE = "config.json"
TZ = pytz.timezone("America/Caracas")  # UTC-4

GIF_URL = (
    "https://blogger.googleusercontent.com/img/b/R29vZ2xl/"
    "AVvXsEhgjGA2lzs-pgUhRrGYImfMvrjRFkGnili3j9_rSSnll0F83NELGw0q3zqjJtPJ1Wcb7aPq5KS2wtfBn"
    "DZTre8V1swHgrJ1Ec_I-087cInEOsic_6sbaTqsEx0UGUlY97w8vh1zU5RzjsXNSfBXIlmTmDOWrdo4oE8nux"
    "kxHSkP33y4Lard0BsQGvV3kGM/s600/doc_2026-03-04_19-31-59.gif"
)

ASK_PASSWORD, ASK_CHANNEL = range(2)
GFA_PASSWORD = "gfa1234"

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

LEAGUES = {
    # Alemania
    "ger.1":                      ("🇩🇪", "Bundesliga"),
    "ger.dfb_pokal":              ("🇩🇪", "DFB-Pokal"),
    # España
    "esp.1":                      ("🇪🇸", "LaLiga EA Sports"),
    "esp.copa_del_rey":           ("🇪🇸", "Copa del Rey"),
    "esp.super_cup":              ("🇪🇸", "Supercopa de España"),
    # Francia
    "fra.1":                      ("🇫🇷", "Ligue 1"),
    "fra.coupe_de_france":        ("🇫🇷", "Copa de Francia"),
    # Inglaterra
    "eng.1":                      ("🇬🇧", "Premier League"),
    "eng.fa":                     ("🇬🇧", "FA Cup"),
    "eng.league_cup":             ("🇬🇧", "EFL Cup"),
    "eng.community_shield":       ("🇬🇧", "Community Shield"),
    # Italia
    "ita.1":                      ("🇮🇹", "Serie A"),
    "ita.coppa_italia":           ("🇮🇹", "Copa Italia"),
    # Europa UEFA
    "uefa.champions":             ("🌍", "Champions League"),
    "uefa.europa":                ("🌍", "Europa League"),
    "uefa.europa.conf":           ("🌍", "Conference League"),
    "uefa.nations":               ("🌍", "Nations League"),
    # Clasificatorias europeas Mundial 2026
    "fifa.worldq.uefa":           ("🇪🇺", "Eliminatorias UEFA"),
    # Repescas
    "fifa.worldq.intercontinental": ("🌍", "Repesca Intercontinental"),
    # Selecciones / Internacional
    "fifa.friendly":              ("🌍", "Amistosos Internacionales"),
    "international.friendly":     ("🌍", "Amistosos Internacionales"),
    "fifa.world":                 ("🌍", "Mundial FIFA"),
    "uefa.euro":                  ("🇪🇺", "Eurocopa"),
    "conmebol.america":           ("🌎", "Copa América"),
    "caf.nations":                ("🌍", "Copa Africana de Naciones"),
    # FIFA Series
    "fifa.series":                ("🌍", "FIFA Series"),
    "fifa.series.men":            ("🌍", "FIFA Series"),
    # Eliminatorias CONMEBOL (Venezuela juega aquí)
    "fifa.worldq.conmebol":       ("🌎", "Eliminatorias CONMEBOL"),
    "conmebol.qualifying":        ("🌎", "Eliminatorias CONMEBOL"),
    # Eliminatorias UEFA + Repesca europea
    "fifa.worldq.uefa":           ("🇪🇺", "Eliminatorias UEFA"),
    "uefa.qualifying":            ("🇪🇺", "Repesca Europea"),
    # Eliminatorias CONCACAF
    "fifa.worldq.concacaf":       ("🌎", "Eliminatorias CONCACAF"),
    "concacaf.qualifying":        ("🌎", "Eliminatorias CONCACAF"),
    # Eliminatorias AFC
    "fifa.worldq.afc":            ("🌏", "Eliminatorias AFC"),
    # Eliminatorias CAF
    "fifa.worldq.caf":            ("🌍", "Eliminatorias CAF"),
    # Repescas intercontinentales
    "fifa.worldq.intercontinental": ("🌍", "Repesca Intercontinental"),
    "fifa.worldq.afc.conmebol":   ("🌍", "Repesca AFC/CONMEBOL"),
    # CONMEBOL
    "conmebol.libertadores":      ("🌎", "CONMEBOL Libertadores"),
    "conmebol.sudamericana":      ("🌎", "CONMEBOL Sudamericana"),
    "conmebol.recopa":            ("🌎", "Recopa Sudamericana"),
    # FIFA Intercontinental Cup
    "fifa.intercontinental":      ("🌍", "FIFA Intercontinental Cup"),
}

# ─── Config helpers ────────────────────────────────────────────────────────────

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)

def get_channel_id() -> Optional[str]:
    config = load_config()
    return config.get("channel_id") or CHANNEL_ID_ENV

# ─── Helpers de tiempo ─────────────────────────────────────────────────────────

def get_today_utc4() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")

def espn_date(date_str: str) -> str:
    return date_str.replace("-", "")

def parse_event_time(utc_str: str):
    try:
        dt_utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(TZ)
        return dt_local.strftime("%H:%M"), dt_local
    except Exception:
        return "--:--", None

# Traducciones de términos de ronda ESPN (inglés → español)
ROUND_TRANSLATIONS = {
    "1st leg": "Ida",
    "2nd leg": "Vuelta",
    "round of 16": "Octavos de Final",
    "round of 32": "Dieciseisavos de Final",
    "quarterfinals": "Cuartos de Final",
    "semifinals": "Semifinales",
    "final": "Final",
    "third place": "Tercer Puesto",
    "group stage": "Fase de Grupos",
    "playoff": "Playoff",
    "qualifying": "Clasificación",
    "extra time": "Prórroga",
}

def translate_round(text: str) -> str:
    if not text:
        return ""
    lower = text.strip().lower()
    for eng, esp in ROUND_TRANSLATIONS.items():
        if eng in lower:
            return esp
    return text.strip()

def get_round_name(event: dict) -> str:
    """Extrae el nombre de la ronda/jornada de un evento ESPN de forma segura."""
    try:
        competitions = event.get("competitions", [])
        comp = competitions[0] if competitions else {}

        # 1) notes → headline (ej: "Quarterfinals", "1st Leg")
        notes = comp.get("notes", [])
        if notes and isinstance(notes, list) and isinstance(notes[0], dict):
            headline = notes[0].get("headline", "")
            if headline:
                return translate_round(headline)

        # 2) week.number → "Jornada N"
        week = event.get("week", {})
        if isinstance(week, dict):
            number = week.get("number")
            if number:
                return f"Jornada {number}"

        # 3) season.type → descripción del tipo de fase
        season = event.get("season", {})
        if isinstance(season, dict):
            stype = season.get("type", {})
            if isinstance(stype, dict):
                desc = stype.get("abbreviation") or stype.get("name", "")
                translated = translate_round(str(desc)) if desc else ""
                if translated and translated.lower() not in ("regular season", "temporada regular", "reg"):
                    return translated

        return ""
    except Exception:
        return ""

# ─── API ESPN ──────────────────────────────────────────────────────────────────

def fetch_league(slug: str, date_str: str) -> list:
    try:
        resp = requests.get(
            f"{ESPN_BASE}/{slug}/scoreboard",
            params={"dates": espn_date(date_str), "limit": 100},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("events", [])
    except Exception as e:
        logger.error(f"Error fetching ESPN {slug}: {e}")
        return []

def fetch_matches_for_date(local_date: str) -> dict:
    all_matches: dict = {}

    for slug, (flag, name) in LEAGUES.items():
        events = fetch_league(slug, local_date)

        for event in events:
            utc_str = event.get("date", "")
            time_str, dt_local = parse_event_time(utc_str)

            # Filtrar por fecha local correcta
            if dt_local and dt_local.strftime("%Y-%m-%d") != local_date:
                continue

            round_name = get_round_name(event)

            # Equipos
            competitions = event.get("competitions", [{}])
            comp = competitions[0] if competitions else {}
            competitors = comp.get("competitors", [])
            home = next(
                (c.get("team", {}).get("displayName", "?")
                 for c in competitors if c.get("homeAway") == "home"), "?"
            )
            away = next(
                (c.get("team", {}).get("displayName", "?")
                 for c in competitors if c.get("homeAway") == "away"), "?"
            )

            if slug not in all_matches:
                all_matches[slug] = (flag, name, round_name, [])

            all_matches[slug][3].append({
                "home": home,
                "away": away,
                "time_str": time_str,
                "dt_local": dt_local,
            })

    return all_matches

def fetch_matches() -> dict:
    return fetch_matches_for_date(get_today_utc4())

# ─── Formatter ─────────────────────────────────────────────────────────────────


# --- /debugjson ---

async def debugjson_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Consulta Premier League y muestra el JSON crudo del primer evento
    import json as json_mod
    slug = context.args[0] if context.args else "eng.1"
    date = get_today_utc4()
    events = fetch_league(slug, date)
    if not events:
        await update.message.reply_text(f"No hay eventos para {slug} hoy.")
        return
    ev = events[0]
    # Mostrar campos clave
    keys_to_show = {
        "name": ev.get("name"),
        "date": ev.get("date"),
        "week": ev.get("week"),
        "season": ev.get("season"),
        "competitions[0].notes": ev.get("competitions", [{}])[0].get("notes"),
        "competitions[0].status.type.description": ev.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("description"),
        "competitions[0].situation": ev.get("competitions", [{}])[0].get("situation"),
    }
    text = f"<b>JSON de {slug} — primer evento</b>\n\n"
    for k, v in keys_to_show.items():
        text += f"<code>{k}</code>:\n{json_mod.dumps(v, ensure_ascii=False)}\n\n"
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await update.message.reply_text(chunk, parse_mode="HTML")

def format_message(all_matches: dict) -> str:
    header = "<b>🍿 ¡PARTIDOS DE HOY! ⚽️</b>"
    footer = "<i>⚽️ Suscríbete en t.me/iUniversoFootball</i>"

    if not all_matches:
        return header + "\n\n" + "No hay partidos hoy en las ligas seleccionadas." + "\n\n" + footer

    lines = [header]

    for slug, (flag, name, round_name, matches) in all_matches.items():
        matches_sorted = sorted(
            matches,
            key=lambda m: m["dt_local"] if m["dt_local"] else datetime.max.replace(tzinfo=TZ)
        )

        groups: dict = {}
        for match in matches_sorted:
            groups.setdefault(match["time_str"], []).append(match)

        league_header = f"<b>{flag} | {name}"
        if round_name:
            league_header += f" - {round_name}"
        league_header += "</b>"

        lines.append("")
        lines.append(league_header)
        lines.append("")

        for time_str in list(groups.keys()):
            for match in groups[time_str]:
                lines.append(f"{match['home']} - {match['away']} {time_str}")

    lines.append("")
    lines.append(footer)
    return "\n".join(lines)

# ─── Envío al canal ────────────────────────────────────────────────────────────

async def send_to_channel(bot, channel_id: str, text: str) -> None:
    if len(text) <= 1024:
        await bot.send_animation(
            chat_id=channel_id,
            animation=GIF_URL,
            caption=text,
            parse_mode="HTML",
        )
    else:
        await bot.send_animation(chat_id=channel_id, animation=GIF_URL)
        await bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")

# ─── Scheduler ────────────────────────────────────────────────────────────────

async def send_daily_matches(bot) -> None:
    channel_id = get_channel_id()
    if not channel_id:
        logger.warning("No hay canal configurado.")
        return
    all_matches = fetch_matches()
    msg = format_message(all_matches)
    try:
        await send_to_channel(bot, channel_id, msg)
        logger.info(f"Partidos enviados a {channel_id}")
    except Exception as e:
        logger.error(f"Error al enviar mensaje: {e}")

# ─── /start ────────────────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "crack"
    await update.message.reply_text(
        f"👋 ¡Hola, {name}!\n\n"
        "Soy el bot de <b>iUniversoFootball</b> ⚽️\n"
        "Publico los partidos del día cada noche a las <b>00:00 (UTC-4)</b>.\n\n"
        "📋 <b>Comandos:</b>\n"
        "• /start — Este mensaje\n"
        "• /gfa — Vincula un canal\n"
        "• /test — Envía partidos de hoy\n"
        "• /testfecha YYYY-MM-DD — Prueba con fecha específica\n\n"
        "<i>⚽️ Suscríbete en t.me/iUniversoFootball</i>",
        parse_mode="HTML",
    )

# ─── /test ─────────────────────────────────────────────────────────────────────

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    channel_id = get_channel_id()
    if not channel_id:
        await update.message.reply_text("❌ No hay canal configurado. Usa /gfa primero.")
        return
    await update.message.reply_text("⏳ Buscando partidos de hoy...")
    all_matches = fetch_matches()
    msg = format_message(all_matches)
    try:
        await send_to_channel(context.bot, channel_id, msg)
        await update.message.reply_text(f"✅ Enviado a <code>{channel_id}</code>.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: <code>{e}</code>", parse_mode="HTML")

# ─── /testfecha ────────────────────────────────────────────────────────────────

async def testfecha_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    channel_id = get_channel_id()
    if not channel_id:
        await update.message.reply_text("❌ No hay canal configurado. Usa /gfa primero.")
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("❌ Uso: <code>/testfecha YYYY-MM-DD</code>", parse_mode="HTML")
        return
    fecha = context.args[0]
    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("❌ Fecha inválida. Formato: <code>YYYY-MM-DD</code>", parse_mode="HTML")
        return
    await update.message.reply_text(f"⏳ Buscando partidos del {fecha}...")
    all_matches = fetch_matches_for_date(fecha)
    msg = format_message(all_matches)
    try:
        await send_to_channel(context.bot, channel_id, msg)
        await update.message.reply_text(
            f"✅ Enviado: {fecha} → <code>{channel_id}</code>", parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: <code>{e}</code>", parse_mode="HTML")

# ─── /gfa ──────────────────────────────────────────────────────────────────────

async def gfa_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔐 <b>Vinculación de canal</b>\n\nIngresa la contraseña:", parse_mode="HTML"
    )
    return ASK_PASSWORD

async def gfa_check_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.strip() != GFA_PASSWORD:
        await update.message.reply_text("❌ Contraseña incorrecta. Operación cancelada.")
        return ConversationHandler.END
    await update.message.reply_text(
        "✅ Correcto.\n\nEnvíame el <b>ID del canal</b>.\nEjemplo: <code>-1001234567890</code>",
        parse_mode="HTML",
    )
    return ASK_CHANNEL

async def gfa_save_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    channel_id = update.message.text.strip()
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("❌ No eres administrador de ese canal.")
            return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ No pude verificar.\n<code>{e}</code>", parse_mode="HTML")
        return ConversationHandler.END
    config = load_config()
    config["channel_id"] = channel_id
    save_config(config)
    await update.message.reply_text(
        f"✅ Canal vinculado: <code>{channel_id}</code>\nUsa /test para probar.", parse_mode="HTML"
    )
    return ConversationHandler.END

async def gfa_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END

# ─── post_init ─────────────────────────────────────────────────────────────────

async def post_init(application) -> None:
    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(
        send_daily_matches, trigger="cron", hour=0, minute=0,
        kwargs={"bot": application.bot}
    )
    scheduler.start()
    logger.info("Scheduler iniciado — 00:00 UTC-4.")

# ─── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if not TOKEN:
        raise ValueError("Falta TELEGRAM_TOKEN")

    application = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    gfa_handler = ConversationHandler(
        entry_points=[CommandHandler("gfa", gfa_start)],
        states={
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, gfa_check_password)],
            ASK_CHANNEL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, gfa_save_channel)],
        },
        fallbacks=[CommandHandler("cancel", gfa_cancel)],
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("testfecha", testfecha_command))
    application.add_handler(CommandHandler("debugjson", debugjson_command))
    application.add_handler(gfa_handler)

    logger.info("Bot iniciado...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
