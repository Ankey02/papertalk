"""A small vector store: embeddings are saved in SQLite and searched with NumPy.

Each chunk's embedding is a list of numbers describing its meaning. To answer a
question we embed the question the same way and pick the chunks whose numbers
point in the most similar direction (cosine similarity).
"""
import numpy as np


def to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def add_chunks(conn, doc_id: int, chunks: list[tuple[int, str]], vectors: np.ndarray) -> None:
    conn.executemany(
        "INSERT INTO chunks (doc_id, page, text, embedding) VALUES (?, ?, ?, ?)",
        [
            (doc_id, page, text, to_blob(vector))
            for (page, text), vector in zip(chunks, vectors)
        ],
    )


def replace_embeddings(conn, chunk_ids: list[int], vectors: np.ndarray) -> None:
    conn.executemany(
        "UPDATE chunks SET embedding = ? WHERE id = ?",
        [(to_blob(vector), chunk_id) for chunk_id, vector in zip(chunk_ids, vectors)],
    )


def _rows(conn, doc_ids: list[int]):
    marks = ",".join("?" * len(doc_ids))
    return conn.execute(
        f"""SELECT c.id, c.doc_id, c.page, c.text, c.embedding, d.filename
            FROM chunks c JOIN documents d ON d.id = c.doc_id
            WHERE c.doc_id IN ({marks})
            ORDER BY c.doc_id, c.id""",
        doc_ids,
    ).fetchall()


def _as_source(row, score: float) -> dict:
    return {
        "doc_id": row["doc_id"],
        "filename": row["filename"],
        "page": row["page"],
        "text": row["text"],
        "score": round(float(score), 3),
    }


def search(conn, doc_ids: list[int], query_vector: np.ndarray, k: int) -> list[dict]:
    """The k chunks most similar to the question."""
    rows = _rows(conn, doc_ids)
    if not rows:
        return []
    matrix = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    scores = matrix @ np.asarray(query_vector, dtype=np.float32)
    best = np.argsort(-scores)[:k]
    return [_as_source(rows[i], scores[i]) for i in best]


def sample(conn, doc_ids: list[int], k: int) -> list[dict]:
    """k chunks spread evenly through the documents, for summaries."""
    rows = _rows(conn, doc_ids)
    if not rows:
        return []
    if len(rows) <= k:
        picked = rows
    else:
        positions = np.linspace(0, len(rows) - 1, k).round().astype(int)
        picked = [rows[i] for i in positions]
    return [_as_source(row, 0.0) for row in picked]
