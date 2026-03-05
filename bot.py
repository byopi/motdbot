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

TSDB_KEY = "123"
TSDB_BASE = f"https://www.thesportsdb.com/api/v1/json/{TSDB_KEY}"

ASK_PASSWORD, ASK_CHANNEL = range(2)
GFA_PASSWORD = "gfa1234"

# ─── IDs verificados directamente en thesportsdb.com ──────────────────────────
LEAGUES = {
    # Alemania
    "4331": ("🇩🇪", "Bundesliga"),
    "4485": ("🇩🇪", "DFB-Pokal"),             # ← corregido (era 4398)
    # España
    "4335": ("🇪🇸", "LaLiga EA Sports"),
    "4483": ("🇪🇸", "Copa del Rey"),           # ← corregido (era 4406)
    "4511": ("🇪🇸", "Supercopa de España"),    # ← corregido (era 556)
    # Francia
    "4334": ("🇫🇷", "Ligue 1"),
    "4484": ("🇫🇷", "Copa de Francia"),
    # Inglaterra
    "4328": ("🇬🇧", "Premier League"),
    "4482": ("🇬🇧", "FA Cup"),                 # ← corregido (era 4580)
    "4570": ("🇬🇧", "EFL Cup"),                # ← corregido (era 4443)
    "4571": ("🇬🇧", "Community Shield"),       # ← corregido (era 528)
    # Italia
    "4332": ("🇮🇹", "Serie A"),
    "4506": ("🇮🇹", "Copa Italia"),            # ← corregido (era 4400)
    # Europa
    "4480": ("🌍", "Champions League"),
    "4481": ("🌍", "Europa League"),
    "5071": ("🌍", "Conference League"),       # ← corregido (era 4579)
    "4490": ("🌍", "Nations League"),          # ← corregido (era 4486)
    # Mundial / Internacionales
    "4429": ("🌍", "Mundial FIFA"),            # ← corregido (era 4407)
    "4502": ("🇪🇺", "Eurocopa"),               # ← corregido (era 4408)
    "4499": ("🌎", "Copa América"),            # ← corregido (era 4409)
    "4410": ("🌍", "Copa Africana de Naciones"),
    # Sudamérica
    "4501": ("🌎", "CONMEBOL Libertadores"),   # ← corregido (era 4344)
    "4724": ("🌎", "CONMEBOL Sudamericana"),   # ← corregido (era 4345)
    "5665": ("🌎", "Recopa Sudamericana"),     # ← corregido (era 133604)
}

# Ligas cuyos partidos nocturnos pueden aparecer en UTC como el día siguiente
LATE_NIGHT_LEAGUES = {
    "4501",  # CONMEBOL Libertadores
    "4724",  # CONMEBOL Sudamericana
    "5665",  # Recopa Sudamericana
    "4499",  # Copa América
    "4429",  # Mundial FIFA
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

def parse_event_time(event: dict):
    try:
        timestamp = event.get("strTimestamp") or ""
        if timestamp:
            dt_utc = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone(TZ)
            return dt_local.strftime("%H:%M"), dt_local
        date_str = event.get("dateEvent") or ""
        time_str = (event.get("strTime") or "")[:5]
        if date_str and time_str:
            dt_utc = datetime.fromisoformat(f"{date_str}T{time_str}:00+00:00")
            dt_local = dt_utc.astimezone(TZ)
            return dt_local.strftime("%H:%M"), dt_local
    except Exception:
        pass
    return "--:--", None

def event_local_date(event: dict) -> Optional[str]:
    _, dt_local = parse_event_time(event)
    if dt_local:
        return dt_local.strftime("%Y-%m-%d")
    return None

# ─── API helpers ───────────────────────────────────────────────────────────────

def fetch_events_for_utc_date(utc_date: str) -> list:
    try:
        resp = requests.get(
            f"{TSDB_BASE}/eventsday.php",
            params={"d": utc_date, "s": "Soccer"},
            timeout=15,
        )
        return resp.json().get("events") or []
    except Exception as e:
        logger.error(f"Error consultando TheSportsDB ({utc_date}): {e}")
        return []

def fetch_matches_for_date(local_date: str) -> dict:
    dt_local = datetime.strptime(local_date, "%Y-%m-%d")
    utc_same = local_date
    utc_next = (dt_local + timedelta(days=1)).strftime("%Y-%m-%d")

    events_same = fetch_events_for_utc_date(utc_same)
    events_next = fetch_events_for_utc_date(utc_next)

    all_matches: dict = {}

    def add_event(event):
        league_id = str(event.get("idLeague", ""))
        if league_id not in LEAGUES:
            return
        if event_local_date(event) != local_date:
            return
        flag, name = LEAGUES[league_id]
        round_raw = event.get("intRound") or event.get("strRound") or ""
        if str(round_raw).isdigit():
            round_name = f"Jornada {round_raw}"
        elif round_raw:
            round_name = str(round_raw)
        else:
            round_name = ""
        if league_id not in all_matches:
            all_matches[league_id] = (flag, name, round_name, [])
        existing_ids = {e.get("idEvent") for e in all_matches[league_id][3]}
        if event.get("idEvent") not in existing_ids:
            all_matches[league_id][3].append(event)

    for event in events_same:
        add_event(event)

    for event in events_next:
        if str(event.get("idLeague", "")) in LATE_NIGHT_LEAGUES:
            add_event(event)

    return all_matches

def fetch_matches() -> dict:
    return fetch_matches_for_date(get_today_utc4())

# ─── Formatter ─────────────────────────────────────────────────────────────────

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

        league_header = f"<b>{flag} | {name}"
        if round_name:
            league_header += f" - {round_name}"
        league_header += "</b>"

        lines.append("")
        lines.append(league_header)
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

# ─── /gfa ──────────────────────────────────────────────────────────────────────

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
