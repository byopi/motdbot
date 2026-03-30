from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    # Esta es la respuesta que recibirá UptimeRobot
    return "Bot is running!"

def run():
    # El puerto 8080 es el estándar para servicios web en la nube
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    """
    Inicia el servidor Flask en un hilo separado 
    para que el bot pueda seguir ejecutándose.
    """
    t = Thread(target=run)
    t.start()
