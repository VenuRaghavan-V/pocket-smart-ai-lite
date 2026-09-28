"""
pdf_processor.py
-----------------
Beginner-friendly module to:
1. Extract raw text from a PDF file
2. Split that text into small overlapping chunks

Why chunks? A retrieval index works best on short pieces of text
(a few sentences), not a whole PDF at once. Overlap between chunks
helps preserve context that would otherwise get cut in half.

Deploy note: this LITE build uses `pypdf` (pure Python, ~1 MB, actively
maintained - it is the official successor of PyPDF2) instead of the
heavier PDF stacks. The function signatures are unchanged.
"""

from pypdf import PdfReader
from pypdf.errors import PdfReadError


def extract_text_from_pdf(pdf_path):
    """
    Reads a PDF file and returns all its text as one big string.

    Args:
        pdf_path (str): Path to the PDF file on disk.

    Returns:
        str: All extracted text, joined with newlines.

    Raises:
        ValueError: If the file cannot be read as a PDF (corrupt,
                    password-protected, or not actually a PDF).
    """
    try:
        reader = PdfReader(pdf_path)
    except (PdfReadError, OSError, ValueError) as exc:
        raise ValueError(f"Could not open '{pdf_path}' as a PDF: {exc}") from exc

    if getattr(reader, "is_encrypted", False):
        try:
            # Try an empty password - some "encrypted" PDFs just have
            # restrictions with no real password.
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                "This PDF is password-protected and cannot be read."
            ) from exc

    full_text = ""
    for page in reader.pages:
        try:
            page_text = page.extract_text()
        except Exception:  # noqa: BLE001 - a single bad page shouldn't kill the upload
            page_text = None
        if page_text:  # some pages (e.g. scanned images) may return None
            full_text += page_text + "\n"

    return full_text.strip()


def chunk_text(text, chunk_size=500, chunk_overlap=50):
    """
    Splits a long piece of text into smaller overlapping chunks.

    Args:
        text (str): The full text to split.
        chunk_size (int): Approximate number of characters per chunk.
        chunk_overlap (int): Number of characters shared between
                              consecutive chunks, so context isn't lost
                              at chunk boundaries.

    Returns:
        list[str]: A list of text chunks.
    """
    if not text:
        return []

    if chunk_overlap >= chunk_size:
        # Guard against an infinite loop / zero-progress window.
        chunk_overlap = max(0, chunk_size // 5)

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end].strip()

        if chunk:  # skip empty chunks
            chunks.append(chunk)

        # move the window forward, keeping some overlap
        start += (chunk_size - chunk_overlap)

    return chunks


def process_pdf(pdf_path, chunk_size=500, chunk_overlap=50):
    """
    Convenience function: extract text from a PDF AND chunk it
    in one call.

    Args:
        pdf_path (str): Path to the PDF file.
        chunk_size (int): Characters per chunk.
        chunk_overlap (int): Overlap between chunks.

    Returns:
        list[str]: List of text chunks ready for indexing.
    """
    text = extract_text_from_pdf(pdf_path)
    chunks = chunk_text(text, chunk_size, chunk_overlap)
    return chunks
