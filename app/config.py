"""All settings in one place. Values come from the .env file when present."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

APP_NAME = os.getenv("APP_NAME", "PaperTalk")

# Where the database and uploaded PDFs are stored.
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "app.db"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# AI settings. With no key the app runs in demo mode (keyword search only).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
).rstrip("/")
PROVIDER = "gemini" if GEMINI_API_KEY else "demo"

# Limits and search tuning.
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "400"))
CHUNK_SIZE = 900       # characters per chunk
CHUNK_OVERLAP = 150    # characters shared between neighbouring chunks
TOP_K = 5              # passages sent to the AI for a normal question
OVERVIEW_K = 12        # passages sent for "summarize" style questions
HISTORY_TURNS = 6      # earlier messages the AI can see


def _load_secret_key() -> str:
    """Key that signs the login cookie. Created once and kept in data/."""
    env_key = os.getenv("SECRET_KEY", "").strip()
    if env_key:
        return env_key
    key_file = DATA_DIR / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text().strip()


SECRET_KEY = _load_secret_key()
