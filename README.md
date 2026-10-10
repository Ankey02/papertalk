# PaperTalk: chat with your PDFs

A full-stack Python web app. Upload PDFs, ask questions, and get answers
written from your own documents with the page number of every source.

## Features

- Sign up, log in, log out (each user sees only their own data)
- Upload PDFs by button or drag and drop
- Ask one question across several documents (tick them in the sidebar)
- Answers appear word by word, with a Stop button
- Numbered citations: click one to read the exact passage in the Sources panel
- Saved chat history, one-click Summarize, Copy answer, Export chat to a text file
- Light and dark theme, works on phones
- Demo mode: runs without an AI key so you can try it first

## How to run it

You need Python 3.10 or newer.

```bash
# 1. Open a terminal in this folder, then create a virtual environment
python -m venv .venv

# 2. Turn it on
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Mac or Linux

# 3. Install the libraries
pip install -r requirements.txt

# 4. Start the app
python run.py
```

Open http://127.0.0.1:8000 in your browser and create an account.

## Turning on real AI answers

1. Get a free key at https://aistudio.google.com/apikey
2. Copy `.env.example` to a new file named `.env`
3. Paste the key after `GEMINI_API_KEY=`
4. Stop the app (Ctrl + C) and run `python run.py` again

Documents uploaded in demo mode are re-indexed automatically on the next question.

If you see "model name was not found", Google has renamed a model. Look up the
current free Flash model at https://ai.google.dev/gemini-api/docs/models and put
its name in `GEMINI_CHAT_MODEL` in `.env`.

## How it works

```
Upload PDF -> read text page by page -> cut into chunks -> embed each chunk -> save in SQLite
Question   -> embed the question -> find the closest chunks -> send them to the AI -> stream the answer
```

This pattern is called RAG (retrieval-augmented generation).

## Files

| File | What it does |
|---|---|
| `run.py` | Starts the server |
| `app/main.py` | All pages and API routes (FastAPI) |
| `app/config.py` | Settings read from `.env` |
| `app/db.py` | SQLite tables: users, documents, chunks, chats, messages |
| `app/auth.py` | Password hashing and the login check |
| `app/ingest.py` | Reads the PDF and cuts it into chunks |
| `app/ai.py` | Calls the Gemini API for embeddings and answers; demo mode |
| `app/vectorstore.py` | Saves embeddings and finds the closest chunks with NumPy |
| `app/templates/` | HTML pages (Jinja2) |
| `app/static/` | `style.css` and `app.js` for the main page |
| `data/` | Created on first run: the database and uploaded PDFs |

## Ideas for the next version

- Swap `vectorstore.py` for ChromaDB or FAISS
- Read scanned PDFs with OCR
- Support Word and text files
- Deploy it online (Render or Railway) with PostgreSQL
