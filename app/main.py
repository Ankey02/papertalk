"""The web app: pages, login, and the JSON API used by the main page."""
import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import ai, auth, config, ingest, vectorstore
from .db import get_db, init_db

APP_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=config.APP_NAME, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    same_site="lax",
    max_age=60 * 60 * 24 * 14,  # stay logged in for 14 days
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


def render(request: Request, template: str, **context):
    context.setdefault("app_name", config.APP_NAME)
    return templates.TemplateResponse(request, template, context)


# ------------------------------------------------------------------- pages

@app.get("/")
def home(request: Request):
    user = auth.get_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return render(request, "index.html", user=user, provider=config.PROVIDER)


@app.get("/login")
def login_page(request: Request):
    if auth.get_user(request):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html")


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not auth.verify_password(password, user["password_hash"]):
        return render(request, "login.html", error="Wrong email or password.", email=email)
    request.session["user_id"] = user["id"]
    return RedirectResponse("/", status_code=303)


@app.get("/signup")
def signup_page(request: Request):
    if auth.get_user(request):
        return RedirectResponse("/", status_code=303)
    return render(request, "signup.html")


@app.post("/signup")
def signup(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    name, email = name.strip(), email.strip().lower()
    error = None
    if not name:
        error = "Enter your name."
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        error = "Enter a valid email address."
    elif len(password) < 8:
        error = "The password must be at least 8 characters."
    if error is None:
        with get_db() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                error = "An account with this email already exists."
            else:
                cursor = conn.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, auth.hash_password(password)),
                )
                request.session["user_id"] = cursor.lastrowid
    if error:
        return render(request, "signup.html", error=error, name=name, email=email)
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --------------------------------------------------------------------- API

@app.get("/api/state")
def state(user=Depends(auth.require_user)):
    """Everything the sidebar needs: the user's documents and chats."""
    with get_db() as conn:
        docs = conn.execute(
            "SELECT id, filename, pages, chunks FROM documents WHERE user_id = ? ORDER BY id DESC",
            (user["id"],),
        ).fetchall()
        chats = conn.execute(
            "SELECT id, title, updated_at FROM chats WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
            (user["id"],),
        ).fetchall()
    return {"docs": [dict(d) for d in docs], "chats": [dict(c) for c in chats]}


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...), user=Depends(auth.require_user)):
    """Save a PDF, read it, cut it into chunks and store their embeddings."""
    filename = Path(file.filename or "document.pdf").name
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"The file is larger than {config.MAX_UPLOAD_MB} MB.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Only PDF files can be uploaded.")

    stored_name = f"{uuid.uuid4().hex}.pdf"
    path = config.UPLOAD_DIR / stored_name
    path.write_bytes(data)
    try:
        pages = await run_in_threadpool(ingest.extract_pages, path)
        chunks = ingest.chunk_pages(pages)
        vectors = await ai.embed([text for _, text in chunks])
    except (ingest.IngestError, ai.AIError) as exc:
        path.unlink(missing_ok=True)
        status = 400 if isinstance(exc, ingest.IngestError) else 502
        raise HTTPException(status, str(exc))

    page_count = max(number for number, _ in pages)
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO documents (user_id, filename, stored_name, pages, chunks, provider) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], filename, stored_name, page_count, len(chunks), config.PROVIDER),
        )
        vectorstore.add_chunks(conn, cursor.lastrowid, chunks, vectors)
        doc_id = cursor.lastrowid
    return {"id": doc_id, "filename": filename, "pages": page_count, "chunks": len(chunks)}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int, user=Depends(auth.require_user)):
    with get_db() as conn:
        doc = conn.execute(
            "SELECT stored_name FROM documents WHERE id = ? AND user_id = ?",
            (doc_id, user["id"]),
        ).fetchone()
        if doc is None:
            raise HTTPException(404, "Document not found.")
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    (config.UPLOAD_DIR / doc["stored_name"]).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: int, user=Depends(auth.require_user)):
    with get_db() as conn:
        chat = conn.execute(
            "SELECT id, title FROM chats WHERE id = ? AND user_id = ?", (chat_id, user["id"])
        ).fetchone()
        if chat is None:
            raise HTTPException(404, "Chat not found.")
        rows = conn.execute(
            "SELECT id, role, content, sources FROM messages WHERE chat_id = ? ORDER BY id",
            (chat_id,),
        ).fetchall()
    messages = [
        {"id": r["id"], "role": r["role"], "content": r["content"], "sources": json.loads(r["sources"])}
        for r in rows
    ]
    return {"id": chat["id"], "title": chat["title"], "messages": messages}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: int, user=Depends(auth.require_user)):
    with get_db() as conn:
        deleted = conn.execute(
            "DELETE FROM chats WHERE id = ? AND user_id = ?", (chat_id, user["id"])
        ).rowcount
    if not deleted:
        raise HTTPException(404, "Chat not found.")
    return {"ok": True}


class ChatRequest(BaseModel):
    question: str
    chat_id: int | None = None
    doc_ids: list[int] = []


OVERVIEW_WORDS = re.compile(
    r"\b(summar|overview|key points|main points|main ideas|outline|quiz|"
    r"what is (this|the) (document|pdf|file) about)",
    re.IGNORECASE,
)


def event(kind: str, **data) -> str:
    """One line of the streamed reply. The page reads these one by one."""
    return json.dumps({"type": kind, **data}) + "\n"


@app.post("/api/chat")
async def chat(body: ChatRequest, user=Depends(auth.require_user)):
    """Answer a question. The reply is streamed as JSON lines:
    chat -> sources -> token, token, ... -> done (or error)."""
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Type a question first.")
    if len(question) > 4000:
        raise HTTPException(400, "The question is too long.")

    with get_db() as conn:
        docs = conn.execute(
            "SELECT id, provider FROM documents WHERE user_id = ?", (user["id"],)
        ).fetchall()
        if body.doc_ids:
            docs = [d for d in docs if d["id"] in set(body.doc_ids)]
        if not docs:
            raise HTTPException(400, "Upload a PDF first, then ask your question.")

        # Find or create the chat, then save the question.
        if body.chat_id is not None:
            chat_row = conn.execute(
                "SELECT id, title FROM chats WHERE id = ? AND user_id = ?",
                (body.chat_id, user["id"]),
            ).fetchone()
            if chat_row is None:
                raise HTTPException(404, "Chat not found.")
            chat_id, title = chat_row["id"], chat_row["title"]
        else:
            title = question[:60] + ("..." if len(question) > 60 else "")
            chat_id = conn.execute(
                "INSERT INTO chats (user_id, title) VALUES (?, ?)", (user["id"], title)
            ).lastrowid

        history = conn.execute(
            "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, config.HISTORY_TURNS),
        ).fetchall()
        history = [dict(m) for m in reversed(history)]
        conn.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, 'user', ?)",
            (chat_id, question),
        )
        conn.execute("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,))

    doc_ids = [d["id"] for d in docs]
    stale_ids = [d["id"] for d in docs if d["provider"] != config.PROVIDER]

    async def reply():
        answer = ""
        sources: list[dict] = []
        yield event("chat", id=chat_id, title=title)
        try:
            # Documents indexed before the AI key changed need new embeddings.
            for doc_id in stale_ids:
                yield event("status", text="Re-indexing your documents...")
                with get_db() as conn:
                    rows = conn.execute(
                        "SELECT id, text FROM chunks WHERE doc_id = ? ORDER BY id", (doc_id,)
                    ).fetchall()
                vectors = await ai.embed([r["text"] for r in rows])
                with get_db() as conn:
                    vectorstore.replace_embeddings(conn, [r["id"] for r in rows], vectors)
                    conn.execute(
                        "UPDATE documents SET provider = ? WHERE id = ?",
                        (config.PROVIDER, doc_id),
                    )

            if OVERVIEW_WORDS.search(question):
                # "Summarize this" matches no passage in particular, so take
                # passages spread across the whole document instead.
                with get_db() as conn:
                    sources = vectorstore.sample(conn, doc_ids, config.OVERVIEW_K)
            else:
                # Follow-ups like "give one example of each" only make sense
                # with the previous question, so search with both.
                previous = next(
                    (m["content"] for m in reversed(history) if m["role"] == "user"), ""
                )
                query = f"{previous}\n{question}".strip()
                query_vector = (await ai.embed([query], for_query=True))[0]
                with get_db() as conn:
                    sources = vectorstore.search(conn, doc_ids, query_vector, config.TOP_K)

            yield event("sources", sources=sources)
            async for piece in ai.stream_answer(question, history, sources):
                answer += piece
                yield event("token", text=piece)
            yield event("done")
        except ai.AIError as exc:
            yield event("error", message=str(exc))
        finally:
            # Runs even when the user presses Stop, so partial answers are kept.
            if answer:
                with get_db() as conn:
                    conn.execute(
                        "INSERT INTO messages (chat_id, role, content, sources) "
                        "VALUES (?, 'assistant', ?, ?)",
                        (chat_id, answer, json.dumps(sources)),
                    )

    return StreamingResponse(
        reply(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
