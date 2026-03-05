import os
import json
import logging
import requests
from datetime import datetime
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

# API key gratuita de TheSportsDB (no requiere registro)
TSDB_KEY = "123"
TSDB_BASE = f"https://www.thesportsdb.com/api/v1/json/{TSDB_KEY}"

ASK_PASSWORD, ASK_CHANNEL = range(2)
GFA_PASSWORD = "gfa1234"

# IDs de ligas en TheSportsDB → (flag, nombre)
# Puedes consultar IDs en: https://www.thesportsdb.com/league_list.php?s=Soccer
LEAGUES = {
    "4331": ("🇩🇪", "Bundesliga"),
    "4398": ("🇩🇪", "DFB-Pokal"),
    "4335": ("🇪🇸", "LaLiga EA Sports"),
    "4406": ("🇪🇸", "Copa del Rey"),
    "4328": ("🇬🇧", "Premier League"),
    "4580": ("🇬🇧", "FA Cup"),
    "4443": ("🇬🇧", "EFL Cup"),
    "4334": ("🇫🇷", "Ligue 1"),
    "4399": ("🇫🇷", "Copa de Francia"),
    "4332": ("🇮🇹", "Serie A"),
    "4400": ("🇮🇹", "Copa Italia"),
    "4400": ("🇮🇹", "Copa Italia"),
    "4480": ("🌍", "Champions League"),
    "4481": ("🌍", "Europa League"),
    "4579": ("🌍", "Conference League"),
    "4443": ("🌍", "Nations League"),
    "4344": ("🌎", "CONMEBOL Libertadores"),
    "4345": ("🌎", "CONMEBOL Sudamericana"),
    "133604":("🌎", "Recopa Sudamericana"),
    "4399": ("🌍", "Mundial FIFA"),
    "4408": ("🇪🇺", "Eurocopa"),
    "4409": ("🌎", "Copa América"),
    "4410": ("🌍", "Copa Africana de Naciones"),
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

# ─── API helpers ───────────────────────────────────────────────────────────────

def get_today_utc4() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")

def fetch_matches_for_date(date: str) -> dict:
    """
    TheSportsDB: eventsday.php devuelve TODOS los eventos de fútbol del día.
    Luego filtramos por los IDs de liga que nos interesan.
    """
    try:
        resp = requests.get(
            f"{TSDB_BASE}/eventsday.php",
            params={"d": date, "s": "Soccer"},
            timeout=15,
        )
        data = resp.json()
        events = data.get("events") or []
    except Exception as e:
        logger.error(f"Error consultando TheSportsDB: {e}")
        return {}

    # Agrupar por liga filtrando solo las que nos interesan
    all_matches: dict = {}
    for event in events:
        league_id = str(event.get("idLeague", ""))
        if league_id not in LEAGUES:
            continue

        flag, name = LEAGUES[league_id]
        round_name = event.get("intRound") or event.get("strRound") or ""
        if round_name:
            round_name = f"Jornada {round_name}" if str(round_name).isdigit() else str(round_name)

        if league_id not in all_matches:
            all_matches[league_id] = (flag, name, round_name, [])
        all_matches[league_id][3].append(event)

    return all_matches

def fetch_matches() -> dict:
    return fetch_matches_for_date(get_today_utc4())

# ─── Formatter ─────────────────────────────────────────────────────────────────

def parse_event_time(event: dict) -> tuple:
    """
    TheSportsDB devuelve strTimestamp (UTC) o strTime (hora local del evento).
    Convertimos a UTC-4.
    """
    try:
        timestamp = event.get("strTimestamp") or ""
        if timestamp:
            dt_utc = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone(TZ)
            return dt_local.strftime("%H:%M"), dt_local
        # fallback: strTime viene como "HH:MM:SS+00:00" aprox
        time_str = event.get("strTime", "") or ""
        date_str = event.get("dateEvent", "") or ""
        if date_str and time_str:
            time_str = time_str[:5]  # HH:MM
            dt_utc = datetime.fromisoformat(f"{date_str}T{time_str}:00+00:00")
            dt_local = dt_utc.astimezone(TZ)
            return dt_local.strftime("%H:%M"), dt_local
    except Exception:
        pass
    return "--:--", None

def format_message(all_matches: dict) -> str:
    header = "<b>🍿 ¡PARTIDOS DE HOY! ⚽️</b>"
    footer = "<i>⚽️ Suscríbete en t.me/iUniversoFootball</i>"

    if not all_matches:
        return header + "\n\n" + "No hay partidos hoy en las ligas seleccionadas." + "\n\n" + footer

    lines = [header]

    for league_id, (flag, name, round_name, events) in all_matches.items():
        def sort_key(e):
            _, dt = parse_event_time(e)
            return dt if dt else datetime.max.replace(tzinfo=TZ)

        events_sorted = sorted(events, key=sort_key)

        groups: dict = {}
        for event in events_sorted:
            time_str, _ = parse_event_time(event)
            groups.setdefault(time_str, []).append(event)

        header_line = f"{flag} | {name}"
        if round_name:
            header_line += f" - {round_name}"

        lines.append("")
        lines.append(header_line)
        lines.append("")

        time_slots = list(groups.keys())
        for i, time_str in enumerate(time_slots):
            for event in groups[time_str]:
                home = event.get("strHomeTeam", "?")
                away = event.get("strAwayTeam", "?")
                lines.append(f"{home} - {away} {time_str}")
            if i < len(time_slots) - 1:
                lines.append("")

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

# ─── Scheduler job ─────────────────────────────────────────────────────────────

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
        "Publico automáticamente los partidos del día en el canal "
        "cada noche a las <b>00:00 (UTC-4)</b>.\n\n"
        "📋 <b>Comandos disponibles:</b>\n"
        "• /start — Muestra este mensaje\n"
        "• /gfa — Vincula un canal al bot\n"
        "• /test — Envía los partidos de hoy al canal\n"
        "• /testfecha YYYY-MM-DD — Prueba con una fecha específica\n\n"
        "<i>⚽️ Suscríbete en t.me/iUniversoFootball</i>",
        parse_mode="HTML",
    )

# ─── /test ─────────────────────────────────────────────────────────────────────

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    channel_id = get_channel_id()
    if not channel_id:
        await update.message.reply_text(
            "❌ No hay canal configurado. Usa /gfa para vincularlo primero."
        )
        return

    await update.message.reply_text("⏳ Buscando partidos de hoy...")
    all_matches = fetch_matches()
    msg = format_message(all_matches)

    try:
        await send_to_channel(context.bot, channel_id, msg)
        await update.message.reply_text(
            f"✅ Enviado al canal <code>{channel_id}</code>.",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ No pude enviar al canal.\n<code>{e}</code>",
            parse_mode="HTML",
        )

# ─── /testfecha ────────────────────────────────────────────────────────────────

async def testfecha_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    channel_id = get_channel_id()
    if not channel_id:
        await update.message.reply_text(
            "❌ No hay canal configurado. Usa /gfa para vincularlo primero."
        )
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "❌ Formato incorrecto.\n"
            "Uso: <code>/testfecha YYYY-MM-DD</code>\n"
            "Ejemplo: <code>/testfecha 2026-03-08</code>",
            parse_mode="HTML",
        )
        return

    fecha = context.args[0]
    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(
            "❌ Fecha inválida. Usa el formato <code>YYYY-MM-DD</code>.",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text(f"⏳ Buscando partidos del {fecha}...")
    all_matches = fetch_matches_for_date(fecha)
    msg = format_message(all_matches)

    try:
        await send_to_channel(context.bot, channel_id, msg)
        await update.message.reply_text(
            f"✅ Partidos del {fecha} enviados al canal <code>{channel_id}</code>.",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ No pude enviar al canal.\n<code>{e}</code>",
            parse_mode="HTML",
        )

# ─── /gfa — ConversationHandler ────────────────────────────────────────────────

async def gfa_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔐 <b>Vinculación de canal</b>\n\nIngresa la contraseña para continuar:",
        parse_mode="HTML",
    )
    return ASK_PASSWORD

async def gfa_check_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.strip() != GFA_PASSWORD:
        await update.message.reply_text("❌ Contraseña incorrecta. Operación cancelada.")
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ Contraseña correcta.\n\n"
        "Envíame el <b>ID del canal</b> que quieres vincular.\n"
        "Ejemplo: <code>-1001234567890</code>\n\n"
        "<i>Asegúrate de que el bot sea administrador del canal.</i>",
        parse_mode="HTML",
    )
    return ASK_CHANNEL

async def gfa_save_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    channel_id = update.message.text.strip()
    user_id = update.effective_user.id

    try:
        member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("❌ No eres administrador de ese canal. Cancelado.")
            return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(
            f"❌ No pude verificar el canal.\n<code>{e}</code>",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    config = load_config()
    config["channel_id"] = channel_id
    save_config(config)

    await update.message.reply_text(
        f"✅ ¡Canal vinculado!\n\n"
        f"📢 Canal: <code>{channel_id}</code>\n"
        f"🕛 Publicación diaria a las <b>00:00 (UTC-4)</b>.\n\n"
        f"Usa /test para enviar un mensaje de prueba ahora mismo.",
        parse_mode="HTML",
    )
    return ConversationHandler.END

async def gfa_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END

# ─── post_init ─────────────────────────────────────────────────────────────────

async def post_init(application) -> None:
    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(
        send_daily_matches,
        trigger="cron",
        hour=0,
        minute=0,
        kwargs={"bot": application.bot},
    )
    scheduler.start()
    logger.info("Scheduler iniciado — publicación diaria a las 00:00 UTC-4.")

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
    application.add_handler(gfa_handler)

    logger.info("Bot iniciado...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
