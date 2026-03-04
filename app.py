import os
import asyncio
import threading
import logging
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

def start_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # Flask corre en un hilo aparte (solo para mantener vivo el proceso en Render)
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # El bot corre en el hilo principal con su propio event loop
    run_bot()
