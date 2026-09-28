"""
vector_store.py  (LITE)
-----------------------
A tiny, dependency-free replacement for the previous
sentence-transformers + FAISS pair.

WHY THIS FILE CHANGED
    sentence-transformers pulls in PyTorch (hundreds of MB installed)
    and faiss-cpu adds ~30 MB more. That blows the 500 MB deploy budget
    of Vercel/Render free tiers. This class implements the classic BM25
    ranking function using nothing but the Python standard library
    (math + collections + unicodedata + json), which keeps the whole
    deployed bundle at a few dozen MB while still providing good keyword
    relevance retrieval for PDF question answering.

    BM25 is the same family of algorithm used by Lucene/Elasticsearch
    for keyword search: it rewards chunks that contain the query terms
    often, penalises very long chunks, and discounts terms that appear
    in almost every chunk.

PUBLIC API (unchanged, so rag_service.py / rag.py / app.py still work)
    store = VectorStore(index_path="data/rag_index.json")
    store.add_texts(["chunk 1", "chunk 2"])
    store.search("my question", top_k=3)
    store.is_empty()
    store.reset()

The index (the extracted PDF text) is persisted as JSON so the app can
survive a restart - on a serverless host that means a warm instance can
keep answering questions about the PDF it already parsed.
"""

import json
import math
import os
import tempfile
import unicodedata
from collections import Counter

# BM25 tuning constants
K1 = 1.5
B = 0.75

# Token characters: letters (L), numbers (N) and combining marks (M).
# Combining marks matter a lot for Tamil: the virama and vowel signs are
# Unicode "Mn" characters, which Python's regex \w does NOT match. Using
# \w alone would split "வணக்கம்" into fragments, so we classify each
# character instead of using a regular expression.
_WORD_CATEGORY_PREFIXES = ("L", "N", "M")


def _is_word_char(char: str) -> bool:
    """True for letters/numbers/combining marks, False for punctuation/space."""
    return unicodedata.category(char)[0] in _WORD_CATEGORY_PREFIXES


def tokenize(text: str):
    """Lowercase the text and split it into searchable word tokens."""
    if not text:
        return []

    tokens = []
    buffer = []
    for char in text.lower():
        if _is_word_char(char):
            buffer.append(char)
        elif buffer:
            # Whitespace / punctuation ends the current token.
            tokens.append("".join(buffer))
            buffer = []
    if buffer:
        tokens.append("".join(buffer))
    return tokens


class VectorStore:
    """An in-memory (optionally persisted) BM25 keyword search index."""

    def __init__(self, index_path=None, k1=K1, b=B):
        """
        Args:
            index_path (str): Optional JSON file used to persist chunks.
            k1, b: BM25 parameters (defaults are the usual values).
        """
        self.index_path = index_path
        self.k1 = k1
        self.b = b

        self.text_chunks = []        # list[str]
        self._term_freqs = []        # list[Counter] per chunk
        self._chunk_lengths = []     # list[int] per chunk
        self._doc_freq = Counter()   # how many chunks contain each term
        self._avg_length = 0.0
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading / saving
    # ------------------------------------------------------------------
    def _load(self):
        """Read the persisted chunks (if any). Called once, lazily."""
        self._loaded = True
        if not self.index_path or not os.path.exists(self.index_path):
            return
        try:
            with open(self.index_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            chunks = payload.get("chunks") or []
        except (OSError, ValueError):
            # A corrupt cache must never break the app - start clean.
            return

        if chunks:
            self.text_chunks = [str(chunk) for chunk in chunks]
            self._rebuild_stats()

    def _save(self):
        """Persist the chunks so they can be reused after a restart."""
        if not self.index_path:
            return
        directory = os.path.dirname(self.index_path) or "."
        os.makedirs(directory, exist_ok=True)
        try:
            # Write to a temp file first, then replace - so a crash halfway
            # through can never leave a half-written JSON file behind.
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
            ) as handle:
                json.dump(
                    {"chunks": self.text_chunks, "chunk_overlap": 50},
                    handle,
                    ensure_ascii=False,
                )
                temp_path = handle.name
            os.replace(temp_path, self.index_path)
        except OSError:
            # Persisting is best-effort only (e.g. read-only filesystem).
            pass

    def _rebuild_stats(self):
        """Recompute term frequencies / document frequencies for BM25."""
        self._term_freqs = [Counter(tokenize(chunk)) for chunk in self.text_chunks]
        self._chunk_lengths = [
            sum(freqs.values()) or 1 for freqs in self._term_freqs
        ]
        self._doc_freq = Counter()
        for freqs in self._term_freqs:
            self._doc_freq.update(freqs.keys())
        if self._chunk_lengths:
            self._avg_length = sum(self._chunk_lengths) / len(self._chunk_lengths)
        else:
            self._avg_length = 0.0
        self._loaded = True

    def _ensure_loaded(self):
        if not self._loaded:
            self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def add_texts(self, chunks):
        """
        Add text chunks to the index.

        Args:
            chunks (list[str]): Text chunks to add.
        """
        self._ensure_loaded()
        if not chunks:
            return

        # A new PDF replaces the previous one (single-document RAG).
        self.text_chunks = [str(chunk) for chunk in chunks]
        self._rebuild_stats()
        self._save()

    def search(self, query, top_k=3):
        """
        Return the most relevant text chunks for a query, best match first.

        Args:
            query (str): The user's question or search text.
            top_k (int): How many top matches to return.

        Returns:
            list[str]: Relevant chunks. If no term matches at all we still
            return the first chunks, so the model has something to read
            (e.g. for the question "what is this document about?").
        """
        self._ensure_loaded()
        if self.is_empty():
            return []

        query_terms = tokenize(query)
        chunk_count = len(self.text_chunks)

        scored = []
        for index, freqs in enumerate(self._term_freqs):
            score = 0.0
            length = self._chunk_lengths[index] or 1
            for term in query_terms:
                term_freq = freqs.get(term, 0)
                if not term_freq:
                    continue
                doc_freq = self._doc_freq.get(term, 0)
                # BM25 idf (always positive because of the +1)
                idf = math.log(
                    1 + (chunk_count - doc_freq + 0.5) / (doc_freq + 0.5)
                )
                denominator = term_freq + self.k1 * (
                    1 - self.b + self.b * length / (self._avg_length or 1)
                )
                score += idf * (term_freq * (self.k1 + 1)) / denominator
            if score > 0:
                scored.append((score, index))

        if not scored:
            return self.text_chunks[:top_k]

        # Highest score first; ties resolved by original document order.
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self.text_chunks[index] for _, index in scored[:top_k]]

    def is_empty(self):
        """True if no text has been added to the store yet."""
        self._ensure_loaded()
        return len(self.text_chunks) == 0

    def reset(self):
        """Clear the store completely (chunks + persisted JSON)."""
        self.text_chunks = []
        self._term_freqs = []
        self._chunk_lengths = []
        self._doc_freq = Counter()
        self._avg_length = 0.0
        self._loaded = True
        if self.index_path and os.path.exists(self.index_path):
            try:
                os.remove(self.index_path)
            except OSError:
                pass

    def stats(self):
        """Small helper used by /api/health and the smoke test."""
        self._ensure_loaded()
        return {
            "chunks": len(self.text_chunks),
            "vocabulary": len(self._doc_freq),
            "avg_chunk_length": round(self._avg_length, 1),
        }
