"""
config.py  (Pocket Smart AI - LITE deploy edition)
--------------------------------------------------
Central place for all configuration values.

The only behavioural change compared to the full desktop build is
STORAGE_ROOT: on a normal machine the SQLite chat history + uploaded
PDFs are written into the project folder, while on a read-only
serverless host (Vercel / AWS Lambda) the app transparently falls back
to the operating system's temp directory.

All environment variables are optional except GROQ_API_KEY:

    GROQ_API_KEY            Groq API key (required for chat)
    GROQ_MODEL              Groq model id (default llama-3.3-70b-versatile)
    SECRET_KEY              Flask session signing key
    FLASK_DEBUG             True/False (default False)
    MAX_UPLOAD_MB           Max PDF size in MB (default 16, use 4 on Vercel)
    POCKET_AI_STORAGE_DIR   Force the writable storage folder
"""

import os
import tempfile

from dotenv import load_dotenv

# Load variables from a local .env file (if present)
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _is_writable(path: str) -> bool:
    """Return True when we may create/replace files inside `path`."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_probe")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _resolve_storage_root() -> str:
    """
    Project folder on a normal host, OS temp dir on a read-only host.

    Vercel's filesystem is read-only apart from /tmp, so the write probe
    above is all we need to decide - no host-specific env var required.
    """
    override = os.getenv("POCKET_AI_STORAGE_DIR")
    if override:
        root = os.path.abspath(override)
        os.makedirs(root, exist_ok=True)
        return root

    if _is_writable(BASE_DIR):
        return BASE_DIR

    root = os.path.join(tempfile.gettempdir(), "pocket-smart-ai")
    os.makedirs(root, exist_ok=True)
    return root


class Config:
    # --- Flask ---
    SECRET_KEY = os.getenv("SECRET_KEY", "pocket-smart-ai-dev-secret")
    DEBUG = os.getenv("FLASK_DEBUG", "False").strip().lower() in ("1", "true", "yes")

    # --- Groq AI ---
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # --- Where the app is allowed to write ---
    BASE_DIR = BASE_DIR
    STORAGE_ROOT = _resolve_storage_root()
    DATA_DIR = os.path.join(STORAGE_ROOT, "data")
    UPLOAD_FOLDER = os.path.join(STORAGE_ROOT, "uploads")

    # --- Database + RAG index ---
    DB_PATH = os.path.join(DATA_DIR, "chat_history.db")
    RAG_INDEX_PATH = os.path.join(DATA_DIR, "rag_index.json")

    # --- Uploads (PDF for RAG) ---
    ALLOWED_UPLOAD_EXTENSIONS = {"pdf"}
    # Vercel caps request bodies at 4.5 MB, so set MAX_UPLOAD_MB=4 there.
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "16")) * 1024 * 1024

    # --- App identity (used in AI system prompt + UI) ---
    APP_NAME = "Pocket Smart AI"
    MASCOT_NAME = "Sparko"

    # --- Feature flags ---
    ENABLE_PDF_QA = True
    ENABLE_NOTES_MANAGER = False
    ENABLE_TASK_MANAGER = False
    ENABLE_DASHBOARD = False


def ensure_dirs():
    """Create the writable folders. Safe to call as many times as you like."""
    os.makedirs(Config.DATA_DIR, exist_ok=True)
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
