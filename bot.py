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
API_KEY = os.environ.get("API_FOOTBALL_KEY")
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

SEASON_EURO = 2025  # temporada 2025/2026 — actualizar a 2026 en agosto

LEAGUES = {
    78:  ("🇩🇪", "Bundesliga",               True),
    81:  ("🇩🇪", "DFB-Pokal",                True),
    140: ("🇪🇸", "LaLiga EA Sports",          True),
    143: ("🇪🇸", "Copa del Rey",              True),
    556: ("🇪🇸", "Supercopa de España",       True),
    61:  ("🇫🇷", "Ligue 1",                   True),
    66:  ("🇫🇷", "Copa de Francia",           True),
    39:  ("🇬🇧", "Premier League",            True),
    45:  ("🇬🇧", "FA Cup",                    True),
    48:  ("🇬🇧", "EFL Cup",                   True),
    528: ("🇬🇧", "Community Shield",          True),
    135: ("🇮🇹", "Serie A",                   True),
    137: ("🇮🇹", "Copa Italia",               True),
    547: ("🇮🇹", "Supercopa de Italia",       True),
    1:   ("🌍",  "Mundial FIFA",              False),
    4:   ("🇪🇺", "Eurocopa",                  False),
    9:   ("🌎",  "Copa América",              False),
    6:   ("🌍",  "Copa Africana de Naciones", False),
    5:   ("🌍",  "Nations League",            True),
    2:   ("🌍",  "Champions League",          True),
    848: ("🌍",  "Conference League",         True),
    3:   ("🌍",  "Europa League",             True),
    13:  ("🌎",  "CONMEBOL Libertadores",     False),
    11:  ("🌎",  "CONMEBOL Sudamericana",     False),
    541: ("🌎",  "Recopa Sudamericana",       False),
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
    season_intl = int(date[:4])
    headers = {
        "x-rapidapi-key": API_KEY,
        "x-rapidapi-host": "v3.football.api-sports.io",
    }
    all_matches = {}
    for league_id, (flag, name, is_euro) in LEAGUES.items():
        season = SEASON_EURO if is_euro else season_intl
        try:
            resp = requests.get(
                "https://v3.football.api-sports.io/fixtures",
                headers=headers,
                params={"league": league_id, "date": date, "season": season},
                timeout=10,
            )
            fixtures = resp.json().get("response", [])
            if fixtures:
                all_matches[league_id] = (flag, name, fixtures)
        except Exception as e:
            logger.error(f"Error fetching league {league_id} ({name}): {e}")
    return all_matches

def fetch_matches() -> dict:
    return fetch_matches_for_date(get_today_utc4())

# ─── /debug ────────────────────────────────────────────────────────────────────
# Consulta 3 ligas clave con distintas combinaciones de temporada
# y te muestra la respuesta cruda para diagnosticar el problema

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Usa la fecha del argumento o hoy
    if context.args:
        date = context.args[0]
    else:
        date = get_today_utc4()

    headers = {
        "x-rapidapi-key": API_KEY,
        "x-rapidapi-host": "v3.football.api-sports.io",
    }

    # Ligas de prueba: Premier (39), Copa de Francia (66), Libertadores (13)
    test_cases = [
        (39,  "Premier League",       [2024, 2025, 2026]),
        (66,  "Copa de Francia",      [2024, 2025, 2026]),
        (13,  "CONMEBOL Libertadores",[2024, 2025, 2026]),
    ]

    msg_lines = [f"🔍 <b>DEBUG — {date}</b>\n"]

    for league_id, name, seasons in test_cases:
        msg_lines.append(f"<b>{name} (id={league_id})</b>")
        for season in seasons:
            try:
                resp = requests.get(
                    "https://v3.football.api-sports.io/fixtures",
                    headers=headers,
                    params={"league": league_id, "date": date, "season": season},
                    timeout=10,
                )
                data = resp.json()
                count = len(data.get("response", []))
                errors = data.get("errors", [])
                remaining = data.get("parameters", {})
                msg_lines.append(f"  season={season} → {count} partidos | errors={errors}")
            except Exception as e:
                msg_lines.append(f"  season={season} → ERROR: {e}")
        msg_lines.append("")

    # También muestra cuántas requests quedan en la API key
    try:
        resp = requests.get(
            "https://v3.football.api-sports.io/status",
            headers=headers,
            timeout=10,
        )
        status = resp.json().get("response", {})
        requests_used = status.get("requests", {})
        msg_lines.append(
            f"📊 <b>API Status:</b> {requests_used.get('current', '?')} / "
            f"{requests_used.get('limit_day', '?')} requests usadas hoy"
        )
    except Exception as e:
        msg_lines.append(f"📊 API Status error: {e}")

    await update.message.reply_text("\n".join(msg_lines), parse_mode="HTML")

# ─── Formatter ─────────────────────────────────────────────────────────────────

def parse_local_time(utc_str: str):
    try:
        dt_utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(TZ)
        return dt_local.strftime("%H:%M"), dt_local
    except Exception:
        return "--:--", None

def format_message(all_matches: dict) -> str:
    header = "<b>🍿 ¡PARTIDOS DE HOY! ⚽️</b>"
    footer = "<i>⚽️ Suscríbete en t.me/iUniversoFootball</i>"

    if not all_matches:
        return header + "\n\n" + "No hay partidos hoy en las ligas seleccionadas." + "\n\n" + footer

    lines = [header]
    for league_id, (flag, name, fixtures) in all_matches.items():
        round_name = fixtures[0]["league"].get("round", "")

        def sort_key(m):
            _, dt = parse_local_time(m["fixture"]["date"])
            return dt if dt else datetime.max.replace(tzinfo=TZ)

        fixtures_sorted = sorted(fixtures, key=sort_key)
        groups: dict = {}
        for match in fixtures_sorted:
            time_str, _ = parse_local_time(match["fixture"]["date"])
            groups.setdefault(time_str, []).append(match)

        lines.append("")
        lines.append(f"{flag} | {name} - {round_name}")
        lines.append("")

        time_slots = list(groups.keys())
        for i, time_str in enumerate(time_slots):
            for match in groups[time_str]:
                home = match["teams"]["home"]["name"]
                away = match["teams"]["away"]["name"]
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
    if not API_KEY:
        raise ValueError("Falta API_FOOTBALL_KEY")

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
    application.add_handler(CommandHandler("debug", debug_command))
    application.add_handler(gfa_handler)

    logger.info("Bot iniciado...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
