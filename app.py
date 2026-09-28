"""
app.py  (Pocket Smart AI - LITE deploy edition)
-----------------------------------------------
Main Flask entry point.

Workflow implemented here:
    User -> Text/Voice Input -> Speech-to-Text -> Groq AI -> Response -> History
    User -> PDF Upload -> RAG index -> retrieved context injected into chat

Routes are intentionally thin: they just glue together core/database.py,
core/language_utils.py, core/groq_service.py and modules/rag.py.

DEPLOYMENT NOTES
    * This module exposes `app` (a WSGI callable) at the top level, which is
      exactly what Vercel's Python runtime looks for: because the Flask
      instance is named `app` inside app.py, Vercel auto-detects the project
      as a Flask app and needs no vercel.json at all.
    * `application = app` is an alias for WSGI servers (gunicorn/uwsgi) that
      look for a variable called `application`.
    * Storage paths come from config.py, which automatically falls back to
      the OS temp directory on a read-only serverless filesystem.
"""

import os

from flask import Flask, jsonify, render_template, request, session
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from config import Config, ensure_dirs
from core.database import clear_history, get_history, init_db, save_message
from core.groq_service import get_ai_reply
from core.language_utils import detect_language, language_label
from modules.rag import (
    get_rag_context,
    get_rag_status,
    handle_pdf_upload,
    is_pdf_uploaded,
)

NO_PDF_MESSAGE = "Please upload a PDF first."


def _resolve_folder(name: str) -> str:
    """
    Point Flask at <project>/templates and <project>/static.

    Absolute paths are used deliberately: on Vercel the working directory
    is not the project folder, so relying on relative paths (the default
    Flask behaviour) can make templates 500 even though the files are
    present in the bundle.
    """
    candidate = os.path.join(Config.BASE_DIR, name)
    return candidate if os.path.isdir(candidate) else name


app = Flask(
    __name__,
    template_folder=_resolve_folder("templates"),
    static_folder=_resolve_folder("static"),
)
app.config.from_object(Config)

# Make sure the writable folders exist (project folder locally, temp dir
# on serverless hosts) and create the SQLite table on startup.
ensure_dirs()
init_db()

UPLOAD_FOLDER = Config.UPLOAD_FOLDER

# Alias so WSGI servers that look for `application` also work.
application = app


def get_session_id() -> str:
    """Give each browser tab/user a stable session id for chat history."""
    if "session_id" not in session:
        session["session_id"] = os.urandom(16).hex()
    return session["session_id"]


def is_allowed_upload(filename: str) -> bool:
    """Only allow PDF files to be uploaded."""
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in Config.ALLOWED_UPLOAD_EXTENSIONS


@app.route("/")
def index():
    """Serve the chat UI."""
    get_session_id()
    return render_template(
        "index.html",
        app_name=Config.APP_NAME,
        mascot_name=Config.MASCOT_NAME,
    )


@app.route("/api/history", methods=["GET"])
def api_history():
    """Return saved chat history for the current session."""
    session_id = get_session_id()
    history = get_history(session_id)
    return jsonify({"history": history})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """
    Main chat endpoint. Accepts JSON: { "message": "..." }
    Used for both typed text AND transcribed voice text (the frontend
    turns speech into text first, then calls this same endpoint - one
    code path for both input methods, per the required workflow).
    """
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()

    if not user_message:
        return jsonify({"error": "Message cannot be empty."}), 400

    session_id = get_session_id()

    # 1. Detect language automatically (Tamil vs English)
    language = detect_language(user_message)

    # 2. Load PRIOR history first (before saving this turn), so the
    #    current message isn't sent to the model twice - once from
    #    history and once as the "live" turn below.
    history = get_history(session_id)

    # 3. Save the user's message (raw, unmodified - what they actually typed)
    save_message(session_id, "user", user_message, language)

    # 4. RAG: pull relevant context from an uploaded PDF, if any
    rag_context = get_rag_context(user_message)
    prompt_message = user_message
    if rag_context != NO_PDF_MESSAGE:
        prompt_message = (
            f"Context from the uploaded PDF:\n{rag_context}\n\n"
            f"Question:\n{user_message}"
        )

    try:
        # 5. Ask Groq for a reply
        ai_reply = get_ai_reply(prompt_message, language, history)
    except Exception as exc:
        return jsonify({"error": f"AI service error: {exc}"}), 500

    # 6. Save the assistant's reply
    save_message(session_id, "assistant", ai_reply, language)

    return jsonify({
        "reply": ai_reply,
        "language": language,
        "language_label": language_label(language),
    })


@app.route("/upload_pdf", methods=["POST"])
def upload_pdf():
    """Handle a PDF upload and index it for RAG-based question answering."""
    if "pdf_file" not in request.files:
        return jsonify({"success": False, "message": "No file uploaded"}), 400

    file = request.files["pdf_file"]

    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected"}), 400

    if not is_allowed_upload(file.filename):
        return jsonify({
            "success": False,
            "message": "Only PDF files are supported.",
        }), 400

    filename = secure_filename(file.filename)
    save_path = os.path.join(UPLOAD_FOLDER, filename)

    try:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        file.save(save_path)
    except OSError as exc:
        return jsonify({
            "success": False,
            "message": f"Could not save the uploaded file: {exc}",
        }), 500

    result = handle_pdf_upload(save_path)
    status_code = 200 if result.get("success") else 422
    return jsonify(result), status_code


@app.route("/api/pdf-status", methods=["GET"])
def api_pdf_status():
    """Lets the frontend check whether a PDF is currently indexed."""
    return jsonify({"pdf_uploaded": is_pdf_uploaded()})


@app.route("/api/clear", methods=["POST"])
def api_clear():
    """Clear chat history for the current session ('New Chat' button)."""
    session_id = get_session_id()
    clear_history(session_id)
    return jsonify({"status": "cleared"})


@app.route("/api/health", methods=["GET"])
def api_health():
    """
    Lightweight status endpoint - handy for deploy checks, Render's
    healthCheckPath, and for spotting a missing GROQ_API_KEY without
    having to read the logs.
    """
    return jsonify({
        "status": "ok",
        "app": Config.APP_NAME,
        "model": Config.GROQ_MODEL,
        "groq_api_key_configured": bool(Config.GROQ_API_KEY),
        "storage_root": Config.STORAGE_ROOT,
        "max_upload_mb": Config.MAX_CONTENT_LENGTH // (1024 * 1024),
        "rag": get_rag_status(),
    })


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_exc):
    max_mb = Config.MAX_CONTENT_LENGTH // (1024 * 1024)
    return jsonify({
        "success": False,
        "message": f"That file is too large (max {max_mb} MB).",
    }), 413


# ---------------------------------------------------------------------------
# OPTIONAL: server-side voice fallback (for browsers without Web Speech API)
# ---------------------------------------------------------------------------
# The primary voice input path is the browser's built-in Web Speech API
# (see static/js/script.js) - it needs no server work and supports Tamil
# ('ta-IN') and English ('en-IN') out of the box on Chrome/Edge/Android.
#
# This route is an optional fallback using the Python `SpeechRecognition`
# library. It is OFF by default (and its dependencies are NOT in
# requirements.txt, to keep the deploy bundle small) - enable it by
# uncommenting the import + route below and installing:
#     pip install SpeechRecognition pydub   (plus ffmpeg on the host)
#
# from core.voice_fallback import transcribe_audio_file
#
# @app.route("/api/voice-upload", methods=["POST"])
# def api_voice_upload():
#     audio_file = request.files.get("audio")
#     lang_code = request.form.get("lang", "en-IN")
#     if not audio_file:
#         return jsonify({"error": "No audio file received."}), 400
#     text = transcribe_audio_file(audio_file, lang_code)
#     return jsonify({"text": text})


if __name__ == "__main__":
    # Local development only. Vercel/Render import `app` directly instead.
    app.run(debug=Config.DEBUG, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
