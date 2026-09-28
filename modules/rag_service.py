"""
rag_service.py
--------------
The "brain" of the RAG system. It ties together:
  - pdf_processor.py  (extract + chunk PDF text)
  - vector_store.py   (index + search chunks - BM25, no torch/FAISS)

This is the file your Flask app will mostly talk to.

Deploy notes (LITE build):
  * No model download happens at startup or at first upload - the old
    sentence-transformers model (~90 MB download, plus PyTorch) is gone,
    so the first PDF upload is now instant and works offline.
  * The extracted chunks are persisted to Config.RAG_INDEX_PATH, so a
    restarted/Render-redeployed app can still answer questions about the
    last PDF without re-uploading it.
"""

from config import Config

from .pdf_processor import process_pdf
from .vector_store import VectorStore


class RAGService:
    """
    A simple RAG service you can plug into any Flask app.

    Typical flow:
        rag_service = RAGService()
        rag_service.upload_pdf("uploads/my_file.pdf")
        context = rag_service.get_context("What is this document about?")
    """

    def __init__(self):
        self.vector_store = VectorStore(index_path=Config.RAG_INDEX_PATH)
        # Reflect any index that was persisted by an earlier run.
        self.pdf_uploaded = not self.vector_store.is_empty()

    def upload_pdf(self, pdf_path, chunk_size=500, chunk_overlap=50):
        """
        Processes a PDF file: extracts text, splits into chunks,
        and stores the chunks in the search index.

        Args:
            pdf_path (str): Path to the uploaded PDF file.
            chunk_size (int): Characters per chunk.
            chunk_overlap (int): Overlap between chunks.

        Returns:
            dict: A simple status message with chunk count.
        """
        try:
            chunks = process_pdf(pdf_path, chunk_size, chunk_overlap)
        except ValueError as exc:
            # Bad/corrupt/password-protected PDF - fail gracefully.
            return {"success": False, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "message": f"Unexpected error while reading the PDF: {exc}",
            }

        if not chunks:
            return {
                "success": False,
                "message": "Could not extract any text from this PDF. "
                           "It may be a scanned/image-only PDF.",
            }

        try:
            self.vector_store.add_texts(chunks)
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "message": f"Failed to build the search index: {exc}",
            }

        self.pdf_uploaded = True

        return {
            "success": True,
            "message": f"PDF processed successfully. {len(chunks)} chunks created.",
        }

    def get_context(self, query, top_k=3):
        """
        Returns the most relevant chunks of text for a given query,
        joined into a single context string ready to feed to an LLM.

        Args:
            query (str): The user's question.
            top_k (int): How many chunks to retrieve.

        Returns:
            str: Relevant context, OR the required fallback message
                 if no PDF has been uploaded yet.
        """
        # Requirement: if no PDF is uploaded, always return this message
        if not self.pdf_uploaded or self.vector_store.is_empty():
            return "Please upload a PDF first."

        relevant_chunks = self.vector_store.search(query, top_k=top_k)

        if not relevant_chunks:
            return "Please upload a PDF first."

        # Join chunks into one context block, separated for readability
        context = "\n\n---\n\n".join(relevant_chunks)
        return context

    def status(self):
        """Small dict used by the /api/health endpoint."""
        stats = self.vector_store.stats()
        stats["pdf_uploaded"] = self.pdf_uploaded
        return stats

    def reset(self):
        """Clears all uploaded PDF data (e.g. when a user starts over)."""
        self.vector_store.reset()
        self.pdf_uploaded = False
