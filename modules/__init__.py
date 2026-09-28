# -----------------------------------------------------------------------
# Feature modules package
# -----------------------------------------------------------------------
# This package holds self-contained features, e.g.:
#
#   modules/rag.py            -> PDF Question Answering (RAG) - active
#   modules/notes_manager.py  -> Notes Manager (future)
#   modules/task_manager.py   -> Task Manager (future)
#   modules/dashboard.py      -> Dashboard (future)
#
# Suggested pattern for each new module: build it as a Flask Blueprint,
# then in app.py:
#
#   from modules.notes_manager import notes_bp
#   app.register_blueprint(notes_bp)
#
# Deploy note: importing this package must stay cheap - it only imports
# pypdf + the pure-Python BM25 store, no torch / faiss / model download.
# -----------------------------------------------------------------------
from .rag import (
    get_rag_context,
    get_rag_status,
    handle_pdf_upload,
    is_pdf_uploaded,
    reset_rag,
)

__all__ = [
    "handle_pdf_upload",
    "get_rag_context",
    "get_rag_status",
    "reset_rag",
    "is_pdf_uploaded",
]
