import threading
import logging
import os
from flask import Flask
from bot import main as run_bot

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

app = Flask(__name__)

@app.route("/")
def health():
    return "✅ Bot activo", 200

@app.route("/ping")
def ping():
    return "pong", 200

def start_bot():
    run_bot()

if __name__ == "__main__":
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
