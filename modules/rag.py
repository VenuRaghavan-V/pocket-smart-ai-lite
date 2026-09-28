"""
rag.py
-----------------
This is the ONE file your Flask app needs to import.

It creates a single, shared RAGService instance and exposes simple
functions:

    handle_pdf_upload(pdf_path)   -> call this when a user uploads a PDF
    get_rag_context(query)        -> call this before asking your LLM
    get_rag_status()              -> small dict for the health endpoint
    reset_rag()                   -> call this to clear the current PDF
    is_pdf_uploaded()             -> call this to check current RAG state
"""

from .rag_service import RAGService

# A single shared instance used across your whole Flask app.
# (Simple projects only need one RAG "session" at a time.)
_rag_service = RAGService()


def handle_pdf_upload(pdf_path):
    """
    Call this after saving an uploaded PDF file to disk.

    Args:
        pdf_path (str): Full path to the saved PDF file.

    Returns:
        dict: {"success": bool, "message": str}
    """
    return _rag_service.upload_pdf(pdf_path)


def get_rag_context(query, top_k=3):
    """
    Call this to retrieve relevant context for a user's question.

    Args:
        query (str): The user's question.
        top_k (int): Number of chunks to retrieve (default 3).

    Returns:
        str: Relevant text context, or "Please upload a PDF first."
             if no PDF has been uploaded yet.
    """
    return _rag_service.get_context(query, top_k=top_k)


def get_rag_status():
    """Chunk/vocabulary counts for the current PDF (used by /api/health)."""
    return _rag_service.status()


def reset_rag():
    """
    Clears the current PDF and all its stored chunks/vectors.
    Useful if you want to let a user start over with a new PDF.
    """
    _rag_service.reset()
    return {"success": True, "message": "RAG store cleared."}


def is_pdf_uploaded():
    """Returns True if a PDF has already been uploaded and processed."""
    return _rag_service.pdf_uploaded
