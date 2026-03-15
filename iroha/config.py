import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def _env(name: str, default: str = "") -> str:
	return os.getenv(name, default).strip()


BOT_TOKEN = _env("BOT_TOKEN")

DROPBOX_APP_KEY = _env("DROPBOX_APP_KEY")
DROPBOX_APP_SECRET = _env("DROPBOX_APP_SECRET")
DROPBOX_REFRESH_TOKEN = _env("DROPBOX_REFRESH_TOKEN")
DROPBOX_BACKUP_ROOT = _env("DROPBOX_BACKUP_ROOT", "/iroha-backup")

BACKUP_MAX_FILE_MB = int(_env("BACKUP_MAX_FILE_MB", "50"))

LOG_LEVEL = _env("LOG_LEVEL", "INFO")
PORT = int(_env("PORT", "10000"))

BACKUP_ALLOWED_GUILD_IDS = frozenset([1414266396791275683, 1172096674328485948])

SETTINGS_FILE = DATA_DIR / "settings.json"
BACKUP_MANIFEST_FILE = DATA_DIR / "backup_manifest.json"
BACKUP_STATS_FILE = DATA_DIR / "backup_stats.json"
PLAYGAME_FILE = DATA_DIR / "playgame_rooms.json"
HANGOUT_FILE = DATA_DIR / "hangout_events.json"
QUOTES_FILE = DATA_DIR / "quotes.json"
REMINDERS_FILE = DATA_DIR / "reminders.json"


def validate_required_env() -> None:
	if not BOT_TOKEN:
		raise RuntimeError("Missing BOT_TOKEN in environment")
