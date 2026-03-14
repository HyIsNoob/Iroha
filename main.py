import logging
from threading import Thread

from flask import Flask
from waitress import serve

from iroha import config
from iroha.bot import IrohaBot


app = Flask(__name__)


@app.get("/")
def home():
    return "Iroha is running"


@app.get("/health")
def health():
    return {"status": "ok"}


def run_web():
    serve(app, host="0.0.0.0", port=config.PORT, threads=2)


def configure_logging():
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def main():
    config.validate_required_env()
    configure_logging()
    Thread(target=run_web, daemon=True).start()
    bot = IrohaBot()
    bot.run(config.BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
