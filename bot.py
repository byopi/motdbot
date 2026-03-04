import os
import json
import logging
import requests
from datetime import datetime
import pytz
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
API_KEY = os.environ.get("API_FOOTBALL_KEY")
CHANNEL_ID_ENV = os.environ.get("CHANNEL_ID")  # ← fallback permanente
CONFIG_FILE = "config.json"
TZ = pytz.timezone("America/Caracas")  # UTC-4

LEAGUES = {
    78:  ("🇩🇪", "Bundesliga"),
    81:  ("🇩🇪", "DFB-Pokal"),
    140: ("🇪🇸", "LaLiga EA Sports"),
    143: ("🇪🇸", "Copa del Rey"),
    556: ("🇪🇸", "Supercopa de España"),
    61:  ("🇫🇷", "Ligue 1"),
    66:  ("🇫🇷", "Copa de Francia"),
    39:  ("🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Premier League"),
    45:  ("🏴󠁧󠁢󠁥󠁮󠁧󠁿", "FA Cup"),
    48:  ("🏴󠁧󠁢󠁥󠁮󠁧󠁿", "EFL Cup"),
    528: ("🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Community Shield"),
    135: ("🇮🇹", "Serie A"),
    137: ("🇮🇹", "Copa Italia"),
    547: ("🇮🇹", "Supercopa de Italia"),
    1:   ("🌍", "Mundial FIFA"),
    4:   ("🇪🇺", "Eurocopa"),
    9:   ("🌎", "Copa América"),
    6:   ("🌍", "Copa Africana de Naciones"),
    5:   ("🌍", "Nations League"),
    2:   ("🌍", "Champions League"),
    848: ("🌍", "Conference League"),
    3:   ("🌍", "Europa League"),
    13:  ("🌎", "CONMEBOL Libertadores"),
    11:  ("🌎", "CONMEBOL Sudamericana"),
    541: ("🌎", "Recopa Sudamericana"),
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

def get_channel_id() -> str | None:
    """
    Prioridad:
    1. config.json  (guardado por /gfa)
    2. Variable de entorno CHANNEL_ID  (fallback permanente en Render)
    """
    config = load_config()
    return config.get("channel_id") or CHANNEL_ID_ENV

# ─── API helpers ───────────────────────────────────────────────────────────────

def get_today_utc4() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")

def fetch_matches() -> dict:
    date = get_today_utc4()
    season = datetime.now(TZ).year
    headers = {
        "x-rapidapi-key": API_KEY,
        "x-rapidapi-host": "v3.football.api-sports.io",
    }
    all_matches = {}
    for league_id, (flag, name) in LEAGUES.items():
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

# ─── Formatter ─────────────────────────────────────────────────────────────────

def format_message(all_matches: dict) -> str:
    if not all_matches:
        return "No hay partidos hoy en las ligas seleccionadas. ⚽️"
    lines = ["<b>🍿 ¡PARTIDOS DE HOY! ⚽️</b>"]
    for league_id, (flag, name, fixtures) in all_matches.items():
        round_name = fixtures[0]["league"].get("round", "")
        lines.append(f"\n<b>{flag} | {name} - {round_name}</b>")
        for match in fixtures:
            home = match["teams"]["home"]["name"]
            away = match["teams"]["away"]["name"]
            utc_str = match["fixture"]["date"]
            try:
                dt_utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                dt_local = dt_utc.astimezone(TZ)
                time_str = dt_local.strftime("%H:%M")
            except Exception:
                time_str = "--:--"
            lines.append(f"{home} - {away} {time_str}")
    lines.append("\n<i>⚽️ Suscríbete en t.me/iUniversoFootball</i>")
    return "\n".join(lines)

# ─── Scheduler job ─────────────────────────────────────────────────────────────

async def send_daily_matches(bot) -> None:
    channel_id = get_channel_id()
    if not channel_id:
        logger.warning("No hay canal configurado. Usa /gfa o define CHANNEL_ID en Render.")
        return
    all_matches = fetch_matches()
    msg = format_message(all_matches)
    try:
        await bot.send_message(chat_id=channel_id, text=msg, parse_mode="HTML")
        logger.info(f"✅ Partidos enviados a {channel_id}")
    except Exception as e:
        logger.error(f"Error al enviar mensaje: {e}")

# ─── /gfa command ──────────────────────────────────────────────────────────────

async def gfa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) != 2 or args[0] != "gfa1234":
        await update.message.reply_text(
            "❌ Uso incorrecto.\nFormato: <code>/gfa gfa1234 [ID_CANAL]</code>",
            parse_mode="HTML",
        )
        return
    channel_id = args[1]
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("❌ No eres administrador de ese canal.")
            return
    except Exception as e:
        await update.message.reply_text(
            f"❌ No pude verificar el canal.\n<code>{e}</code>",
            parse_mode="HTML",
        )
        return
    config = load_config()
    config["channel_id"] = channel_id
    save_config(config)
    await update.message.reply_text(
        f"✅ Canal configurado: <code>{channel_id}</code>\n"
        "Publicación diaria a las <b>00:00 (UTC-4)</b>.",
        parse_mode="HTML",
    )

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
    logger.info("⏰ Scheduler iniciado — publicación diaria a las 00:00 UTC-4.")

# ─── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if not TOKEN:
        raise ValueError("Falta TELEGRAM_TOKEN")
    if not API_KEY:
        raise ValueError("Falta API_FOOTBALL_KEY")
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("gfa", gfa_command))
    logger.info("🤖 Bot iniciado...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
