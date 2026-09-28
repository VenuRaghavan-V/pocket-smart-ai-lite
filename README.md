# Pocket Smart AI — LITE (deploy edition)

A Flask + Groq bilingual (Tamil / English) chat assistant with voice input,
persistent chat history and PDF question answering (RAG) — repackaged so the
**entire deployed bundle stays far below 500 MB** and deploys with **zero
configuration** on Vercel or Render.

This folder is a drop-in replacement for the full build: the UI, the routes
and the JSON contract are unchanged, so `templates/`, `static/` and the
frontend JavaScript are byte-for-byte the same files.

---

## 1. Why a LITE build — measured size budget

The full build pinned `sentence-transformers`, which pulls in **PyTorch**, plus
`faiss-cpu` and `numpy`. That combination is larger than the 500 MB bundle
limit of Vercel Python Functions, so it could never deploy there.

| Item | Full build | This LITE build |
| --- | --- | --- |
| `torch` (via sentence-transformers) | ~700 MB – 2 GB (estimate) | **removed** |
| `faiss-cpu` | ~30 MB (estimate) | **removed** |
| `numpy` | ~20 MB (estimate) | **removed** |
| `sentence-transformers` | ~15 MB + a ~90 MB model download at first upload | **removed** |
| PyPI packages actually installed | — | **26 MB** (measured) |
| Application code | ~96 KB | **≈95 KB / 27 files** (measured) |
| Whole local virtualenv incl. pip | — | **39 MB** (measured) |
| Compressed source archive | — | **≈41 KB** (measured) |
| **Deployable bundle** | **> 1 GB → rejected** | **≈ 26 MB → 5 % of the 500 MB limit** |

Measurements were taken on this machine with
`python -m venv` + `pip install -r requirements.txt` and `du -sh` over
`Lib/site-packages` (excluding pip's own 12 MB, which is not part of the
runtime), so ≈ **474 MB of headroom** remains. Everything was installed and
tested with **Python 3.13.7**; `.python-version` pins **3.12** for
Vercel/Render and every pinned package ships a matching wheel for it.

### What replaced the embeddings?

`modules/vector_store.py` now implements **BM25** — the keyword-ranking
algorithm used by Lucene/Elasticsearch — in **pure Python** (`math`,
`collections`, `unicodedata`, `json`). Nothing is downloaded at upload time,
the first PDF is indexed instantly, and retrieval works offline.

Extras that came along for free:

* the index is persisted to `data/rag_index.json`, so a warm serverless
  instance (or a restarted Render service) can still answer questions about
  the last PDF without re-uploading it;
* the tokenizer is Unicode-category based, so **Tamil words are kept whole**
  (Tamil vowel signs and the virama are combining marks, which Python's regex
  `\w` does not match — a plain `\w` regex splits `வணக்கம்` into fragments).

---

## 2. Run it locally

```bash
cd pocket-smart-ai-lite
python -m venv venv
venv\Scripts\activate            # Windows (source venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
copy .env.example .env           # then paste your Groq key (https://console.groq.com/keys)
python app.py                    # http://localhost:5000
```

Verify the whole app without a Groq key (36 checks, no network calls):

```bash
python tests/smoke_test.py
```

```
36/36 checks passed
RESULT: ALL CHECKS PASSED
```

---

## 3. Deploy to Vercel (zero configuration)

Vercel's Python runtime looks for a Flask instance named `app` at supported
entrypoints (`app.py`, `index.py`, `server.py`, `main.py`, `wsgi.py`,
`asgi.py`, or the same names inside `src/`/`app/`). This project exposes
exactly that — `app = Flask(...)` in `app.py` — so:

> **No `vercel.json` is required, and adding one is unnecessary.**

1. Push this folder to a GitHub repository.
2. In Vercel: **Add New → Project → Import** that repository. Vercel detects
   Flask from `requirements.txt` automatically (build settings stay default).
3. Add environment variables (Project → Settings → Environment Variables):

   | Name | Value |
   | --- | --- |
   | `GROQ_API_KEY` | your key from https://console.groq.com/keys |
   | `GROQ_MODEL` | `llama-3.3-70b-versatile` |
   | `SECRET_KEY` | any long random string |
   | `MAX_UPLOAD_MB` | `4` |
   | `FLASK_DEBUG` | `False` |

4. Deploy, then open the deployment URL — the chat UI is served by Flask
   itself (templates + static files are installed with the app).

### Vercel platform limits this build respects

| Limit | Value | Handled how |
| --- | --- | --- |
| Python function bundle size | 500 MB uncompressed | bundle ≈ 26 MB |
| Request body size | 4.5 MB | set `MAX_UPLOAD_MB=4`, and `/upload_pdf` returns a clean `413` JSON message above it |
| Filesystem | read-only except `/tmp` | `config.py` probes writability and transparently stores the SQLite DB, the RAG index and uploads in the temp dir when the project folder is not writable |
| Python version | set via `.python-version` | pinned to `3.12` |

Because storage is per-instance and ephemeral on Vercel, chat history and the
PDF index are **not shared across concurrent instances** — that is normal for
serverless, and the app always recreates them on demand.

---

## 4. Deploy to Render

**Blueprint (recommended):** push the folder to GitHub, then
**Render → New → Blueprint** and pick the repository. `render.yaml` creates the
web service (free plan, health check on `/api/health`, gunicorn start command)
and asks you for `GROQ_API_KEY` (`sync: false` keeps the secret out of git).

Manual alternative: create a **Web Service**, runtime *Python 3*,
build command `pip install -r requirements.txt`, start command
`gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`.

> **Free-plan caveat:** Render's free plan has no persistent disk, so the
> SQLite history and the cached PDF index reset on every deploy/restart. To
> keep them, upgrade the plan, add a disk and set
> `POCKET_AI_STORAGE_DIR=/opt/render/project/src/storage`
> (commented example in `render.yaml`).

`Procfile` is included too, for Heroku-style hosts that read it.

---

## 5. Routes (unchanged from the full build, plus one health probe)

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/` | Chat UI |
| GET | `/api/history` | Chat history for the current session |
| POST | `/api/chat` | `{ "message": "..." }` → AI reply + detected language |
| POST | `/upload_pdf` | Upload a PDF (multipart field `pdf_file`) and index it for RAG |
| GET | `/api/pdf-status` | Whether a PDF is currently indexed |
| POST | `/api/clear` | Clear the current session's chat history |
| GET | `/api/health` | **new:** deploy/health-check probe — reports model, storage root, upload cap and index stats, and whether `GROQ_API_KEY` is configured |

## 6. Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | *(empty)* | Groq key — chat returns a clear error until it is set |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model id |
| `SECRET_KEY` | dev string | Flask session signing key |
| `FLASK_DEBUG` | `False` | `True` for local development only |
| `MAX_UPLOAD_MB` | `16` | Max PDF size in MB (use `4` on Vercel) |
| `POCKET_AI_STORAGE_DIR` | auto | Force where DB / index / uploads are written (e.g. a Render disk) |

## 7. Project layout

```
app.py                     Flask entry point + `application` WSGI alias
config.py                  Config incl. serverless-safe storage resolution
core/                      database.py, groq_service.py, language_utils.py, voice_fallback.py
modules/                   rag.py, rag_service.py, pdf_processor.py, vector_store.py (BM25)
static/  templates/        the unchanged UI
data/    uploads/          runtime storage (auto-created, git-ignored)
tests/smoke_test.py        36 offline checks over every route + the retriever
requirements.txt           slim dependency set (26 MB installed)
render.yaml Procfile .python-version .vercelignore .env.example
```

## 8. What was verified on this build

`python tests/smoke_test.py` — **36/36 checks passed**, covering:

* Tamil vs English detection; tokenizer keeps Tamil words whole (`வணக்கம்`);
* BM25 ranking picks the matching chunk, matches Tamil queries, falls back to
  leading chunks when nothing matches, `reset()` empties the store;
* `GET /` renders the UI (200) and the mascot/CSS/JS static files resolve;
* `/api/health`, `/api/pdf-status`, `/api/clear`, empty-message `400`;
* history persistence (4 turns for 2 exchanges) and clearing;
* PDF rejection for non-PDF files, an oversized upload returning `413` with a
  JSON message (the Vercel body-limit path), real PDF extraction + chunking,
  RAG context injected into the prompt with the **relevant** chunk, and the
  index reloading from JSON (warm-instance behaviour);
* the app imports and serves correctly **from a different working directory**,
  and the WSGI callable (`application` / `app`) serves real HTTP responses.

> Note: rendering the UI was verified through Flask's test client and a
> `wsgiref` HTTP server locally. The code was not deployed to a live
> Vercel/Render account from this machine — the configs above follow each
> platform's documented Python requirements, and the bundle size (≈26 MB) is
> well inside the 500 MB limit.

## 9. Trade-offs (please read)

* **Keyword search instead of semantic embeddings.** BM25 matches words (and
  stemming-free morphology), so a question that shares no vocabulary with the
  PDF may retrieve weaker chunks. Mitigations already in place: 3 chunks are
  sent to the model, chunks are 500 characters with 50 characters of overlap,
  and when nothing matches the first chunks are still returned so the model can
  answer "what is this document about?". For study notes, exam papers and
  FAQs — where the question usually reuses the document's wording — quality is
  very close to the embedding version.
* **No model download at all** means no cold-start penalty and no network
  dependency on the first upload.
* If you later want semantic search *without* exceeding the budget, replace
  `modules/vector_store.py` with a hosted embeddings API call (embeddings are
  just `list[float]`; cosine similarity is a few lines of pure Python — no
  torch, no FAISS, no numpy). Keep the same `add_texts` / `search` /
  `is_empty` / `reset` methods and nothing else in the app has to change.
* **Server-side voice fallback stays optional** (`core/voice_fallback.py`):
  its dependencies (SpeechRecognition, pydub, ffmpeg) are deliberately *not*
  installed, because they would grow the bundle for a feature the browser
  already provides via the Web Speech API.
