"""
tests/smoke_test.py
-------------------
Offline verification of the LITE build. Runs the real Flask app through
Flask's own test client and touches every route. It NEVER calls Groq -
the AI call is stubbed - so it is safe and instant to run on any machine.

Also verifies the parts that were rewritten for the deploy budget:
  * the pure-Python BM25 retriever returns the right chunk
  * PDF text extraction (pypdf) + chunking works
  * the index is persisted to JSON and reloads (warm-instance behaviour)

Run it with:
    python tests/smoke_test.py
Exit code 0 = everything passed, 1 = at least one failure.
"""

import io
import os
import sys
import tempfile

# ---------------------------------------------------------------------------
# Point the app at a throw-away storage folder BEFORE anything imports
# config.py, so the test never touches data/ or uploads/ in the project.
# ---------------------------------------------------------------------------
TEMP_STORAGE = tempfile.mkdtemp(prefix="psai-smoke-")
os.environ["POCKET_AI_STORAGE_DIR"] = TEMP_STORAGE
os.environ.pop("GROQ_API_KEY", None)          # prove the app runs without a key
os.environ["SECRET_KEY"] = "smoke-test-secret"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config import Config, ensure_dirs          # noqa: E402
from core.language_utils import detect_language  # noqa: E402
from modules.vector_store import VectorStore, tokenize  # noqa: E402

import app as app_module                         # noqa: E402

ensure_dirs()

RESULTS = []


def check(name, condition, detail=""):
    """Record and print one assertion."""
    ok = bool(condition)
    RESULTS.append((name, ok))
    line = f"{'PASS' if ok else 'FAIL'}  {name}"
    if not ok and detail:
        line += f"   <- {detail}"
    print(line)
    return ok


def build_pdf(path, page_texts):
    """Create a small but genuinely valid PDF (Helvetica, one line per page)."""
    page_count = len(page_texts)
    font_id = 3 + 2 * page_count

    objects = {}
    objects[1] = "<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(page_count))
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>"

    for index, text in enumerate(page_texts):
        page_id = 3 + 2 * index
        content_id = page_id + 1
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        escaped = (
            text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        )
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET"
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
        )

    objects[font_id] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    pdf = "%PDF-1.4\n"
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(pdf.encode("latin-1"))
        pdf += f"{number} 0 obj\n{objects[number]}\nendobj\n"

    xref_offset = len(pdf.encode("latin-1"))
    highest = max(objects)
    pdf += f"xref\n0 {highest + 1}\n0000000000 65535 f \n"
    for number in range(1, highest + 1):
        pdf += f"{offsets.get(number, 0):010d} 00000 n \n"
    pdf += (
        f"trailer\n<< /Size {highest + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    )

    # Binary mode on purpose: text mode would translate \n to \r\n on
    # Windows and shift every byte offset, breaking the xref table.
    with open(path, "wb") as handle:
        handle.write(pdf.encode("latin-1"))
    return path


# ---------------------------------------------------------------------------
# Stub the Groq call so the test never hits the network.
# ---------------------------------------------------------------------------
CAPTURED = {"prompt": None, "language": None, "history": None}


def fake_ai_reply(user_message, language, history):
    CAPTURED["prompt"] = user_message
    CAPTURED["language"] = language
    CAPTURED["history"] = history
    return f"[stubbed {language} reply]"


app_module.get_ai_reply = fake_ai_reply
client = app_module.app.test_client()

PAGE_ONE = (
    "Sparko is the friendly mascot of Pocket Smart AI and helps students "
    "study in Tamil and English. "
) * 8
PAGE_TWO = (
    "Solar panels convert sunlight into electricity using photovoltaic "
    "cells made of silicon semiconductor material. "
) * 8


def run_unit_checks():
    print("-- unit checks --")

    check("language detection: Tamil -> 'ta'",
          detect_language("வணக்கம் நண்பா") == "ta")
    check("language detection: English -> 'en'",
          detect_language("hello there") == "en")

    tamil_tokens = tokenize("வணக்கம் நண்பா hello")
    check("tokenizer keeps Tamil words", "வணக்கம்" in tamil_tokens)
    check("tokenizer lowercases Latin", "hello" in tamil_tokens)

    store = VectorStore()  # in-memory only
    store.add_texts([
        "Cats are small domesticated animals that purr.",
        "Solar panels use photovoltaic cells to make electricity.",
        "தமிழ் மொழி மிகவும் அழகான மொழி.",
    ])
    top = store.search("how do photovoltaic cells work", top_k=1)
    check("BM25 ranks the matching chunk first",
          bool(top) and "photovoltaic" in top[0])
    tamil_top = store.search("தமிழ் மொழி", top_k=1)
    check("BM25 matches Tamil script queries",
          bool(tamil_top) and "தமிழ்" in tamil_top[0])
    check("BM25 falls back to leading chunks when nothing matches",
          store.search("zzzzqqqq", top_k=2)[0].startswith("Cats"))
    check("a fresh store is empty", VectorStore().is_empty() is True)
    store.reset()
    check("reset() empties the store", store.is_empty() is True)


def run_route_checks():
    print("-- route checks --")

    response = client.get("/")
    body = response.get_data(as_text=True)
    check("GET / -> 200", response.status_code == 200)
    check("GET / renders the chat UI",
          "Pocket Smart AI" in body and "chatWindow" in body)
    check("GET / references the mascot asset", "mascot.svg" in body)

    check("GET /static/js/script.js -> 200",
          client.get("/static/js/script.js").status_code == 200)

    health = client.get("/api/health").get_json()
    check("GET /api/health -> status ok",
          health.get("status") == "ok", str(health))
    check("health reports the missing key instead of crashing",
          health["groq_api_key_configured"] is False, str(health))
    check("health reports where it may write",
          bool(health["storage_root"]) and health["max_upload_mb"] >= 4)

    check("GET /api/pdf-status -> False before upload",
          client.get("/api/pdf-status").get_json()["pdf_uploaded"] is False)

    check("POST /api/chat with empty message -> 400",
          client.post("/api/chat", json={"message": ""}).status_code == 400)

    payload = client.post(
        "/api/chat", json={"message": "Hello Sparko, how are you?"}
    ).get_json()
    check("POST /api/chat -> stubbed reply",
          str(payload.get("reply", "")).startswith("[stubbed"), str(payload))
    check("reply carries language metadata",
          payload.get("language") == "en"
          and payload.get("language_label") == "English", str(payload))
    check("no PDF yet -> prompt is not wrapped in Context",
          "Context from the uploaded PDF" not in (CAPTURED["prompt"] or ""))

    tamil_payload = client.post(
        "/api/chat", json={"message": "வணக்கம் ஸ்பார்க்கோ"}
    ).get_json()
    check("Tamil chat detected as 'ta'",
          tamil_payload.get("language") == "ta", str(tamil_payload))

    history = client.get("/api/history").get_json()["history"]
    check("history stored 4 turns (2 user + 2 assistant)",
          len(history) == 4, str(len(history)))


def run_pdf_checks():
    print("-- PDF / RAG checks --")

    response = client.post(
        "/upload_pdf",
        data={"pdf_file": (io.BytesIO(b"not really a pdf"), "notes.txt")},
        content_type="multipart/form-data",
    )
    check("rejects non-PDF uploads", response.status_code == 400,
          str(response.status_code))

    # The 413 path - this is what Vercel returns when MAX_UPLOAD_MB is set to
    # its 4.5 MB request-body ceiling. The real limit is restored afterwards.
    original_limit = app_module.app.config["MAX_CONTENT_LENGTH"]
    app_module.app.config["MAX_CONTENT_LENGTH"] = 512
    try:
        big_pdf = build_pdf(os.path.join(TEMP_STORAGE, "big.pdf"), [PAGE_TWO])
        with open(big_pdf, "rb") as handle:
            response = client.post(
                "/upload_pdf",
                data={"pdf_file": (io.BytesIO(handle.read()), "big.pdf")},
                content_type="multipart/form-data",
            )
        message = (response.get_json() or {}).get("message", "")
        check("oversized upload -> 413 with a JSON message",
              response.status_code == 413 and "too large" in message,
              f"{response.status_code} {message}")
    finally:
        app_module.app.config["MAX_CONTENT_LENGTH"] = original_limit

    pdf_path = build_pdf(
        os.path.join(TEMP_STORAGE, "sample.pdf"), [PAGE_ONE, PAGE_TWO]
    )
    with open(pdf_path, "rb") as handle:
        pdf_bytes = handle.read()

    response = client.post(
        "/upload_pdf",
        data={"pdf_file": (io.BytesIO(pdf_bytes), "sample.pdf")},
        content_type="multipart/form-data",
    )
    result = response.get_json()
    check("POST /upload_pdf succeeds", response.status_code == 200
          and result.get("success") is True, str(result))
    check("upload message reports the chunk count",
          "chunks created" in result.get("message", ""), str(result))

    check("GET /api/pdf-status -> True after upload",
          client.get("/api/pdf-status").get_json()["pdf_uploaded"] is True)

    rag_status = client.get("/api/health").get_json()["rag"]
    check("health reports indexed chunks", rag_status["chunks"] > 1,
          str(rag_status))

    response = client.post(
        "/api/chat", json={"message": "What do photovoltaic cells do?"}
    )
    check("chat still works with a PDF indexed", response.status_code == 200,
          str(response.get_json()))
    captured = CAPTURED["prompt"] or ""
    check("RAG context is injected into the prompt",
          "Context from the uploaded PDF" in captured, captured[:120])
    check("the retrieved chunk is the relevant one",
          "photovoltaic" in captured.lower(), captured[:200])

    reloaded = VectorStore(index_path=Config.RAG_INDEX_PATH)
    check("index is persisted to JSON and reloads (warm instance)",
          "silicon" in (reloaded.search("silicon semiconductor", top_k=1)[0]).lower())

    response = client.post("/api/clear")
    check("POST /api/clear -> status cleared",
          response.get_json().get("status") == "cleared")
    check("history is empty after clear",
          client.get("/api/history").get_json()["history"] == [])

    from modules.rag import reset_rag
    reset_rag()
    check("reset_rag() drops the indexed PDF",
          client.get("/api/pdf-status").get_json()["pdf_uploaded"] is False)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    print("\n=== Pocket Smart AI (LITE) smoke test ===")
    print(f"throw-away storage root: {Config.STORAGE_ROOT}\n")

    run_unit_checks()
    run_route_checks()
    run_pdf_checks()

    failed = [name for name, ok in RESULTS if not ok]
    passed = len(RESULTS) - len(failed)
    print("\n" + "=" * 64)
    print(f"{passed}/{len(RESULTS)} checks passed")
    if failed:
        print("FAILED:")
        for name in failed:
            print(f"  - {name}")
    else:
        print("RESULT: ALL CHECKS PASSED")
    print("=" * 64 + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
