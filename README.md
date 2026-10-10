# PaperTalk

A chat-with-your-PDFs web app built with Python, FastAPI and SQLite. It reads uploaded PDFs, finds the passages closest to a question using embeddings, and streams back an answer that cites the page each fact came from. The pages are served by the API itself.

## What it does

- **Answers questions from your documents** using retrieval-augmented generation (RAG): only passages from the uploaded PDFs are given to the AI model.
- **Cites every answer** with numbered sources. Clicking a number opens the exact passage and page in a side panel.
- **Searches several PDFs at once**: tick the documents to include in the sidebar.
- **Streams answers** word by word over a single HTTP response (`POST /api/chat`), with a Stop button that keeps the partial answer.
- **Accounts and history**: sign up, log in, and every user sees only their own documents and chats.
- **Frontend** with no build step (Jinja2 templates, plain CSS and JavaScript), light and dark theme, works on phones.
- **Demo mode**: runs with no API key, using a keyword-based embedding, so the project can be tried immediately.

## How an answer is made

| Step | What happens | Where |
|---|---|---|
| Read | Text is extracted from the PDF page by page | `app/ingest.py` |
| Chunk | Each page is cut into pieces of about 900 characters with 150 overlapping | `app/ingest.py` |
| Embed | Every chunk becomes a 768-number vector | `app/ai.py` |
| Store | Vectors are saved as BLOBs in SQLite | `app/vectorstore.py` |
| Retrieve | The question is embedded and the 5 closest chunks are found by cosine similarity (NumPy) | `app/vectorstore.py` |
| Generate | The chunks and the question go to the model, which must cite them as `[1]`, `[2]` | `app/ai.py` |

Two details improve retrieval: follow-up questions are searched together with the previous question, and "summarize" style questions take chunks spread evenly across the whole document instead of the top matches.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Database | SQLite (users, documents, chunks, chats, messages) |
| Vector search | NumPy cosine similarity over embeddings stored in SQLite |
| AI | Google Gemini REST API for embeddings and answers, called with httpx |
| PDF reading | pypdf |
| Auth | Signed session cookie, PBKDF2-SHA256 password hashing |
| Frontend | Jinja2, CSS, JavaScript |

## Run it locally

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Open http://127.0.0.1:8000 and create an account.

## Turning on AI answers

Without a key the app runs in demo mode and returns the closest passages instead of a written answer.

1. Create a free key at https://aistudio.google.com/apikey
2. Copy `.env.example` to `.env` and set `GEMINI_API_KEY`
3. Restart the app

Documents uploaded in demo mode are re-indexed automatically on the next question. Model names can be changed in `.env`.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/state` | The user's documents and chats |
| `POST` | `/api/documents` | Upload and index a PDF |
| `DELETE` | `/api/documents/{id}` | Delete a document and its chunks |
| `POST` | `/api/chat` | Ask a question; streams JSON lines (`sources`, `token`, `done`) |
| `GET` | `/api/chats/{id}` | Messages of one chat |
| `DELETE` | `/api/chats/{id}` | Delete a chat |

Interactive API docs are at `/docs` while the app is running.

## Project structure

```
run.py                 starts the server
app/main.py            pages and API routes
app/config.py          settings from .env
app/db.py              SQLite schema and connection helper
app/auth.py            password hashing and login check
app/ingest.py          PDF text extraction and chunking
app/ai.py              Gemini calls and demo mode
app/vectorstore.py     saving and searching embeddings
app/templates/         HTML pages
app/static/            style.css, app.js, logo.svg
```

## Limits

- Scanned PDFs without selectable text are rejected (no OCR yet).
- Uploads are limited to 20 MB and 400 pages.
- Vector search loads a user's selected chunks into memory, which suits personal use rather than very large libraries.
