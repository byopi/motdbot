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
    # Flask en hilo daemon — responde al healthcheck de Render
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Pequeña pausa para que Flask levante el puerto antes de que Render lo verifique
    import time
    time.sleep(2)

    # Bot en hilo principal con su propio event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    run_bot()
