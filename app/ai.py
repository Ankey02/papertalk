"""Everything that talks to the AI model.

Two jobs:
  1. embed(texts)   -> numbers that describe the meaning of each text
  2. stream_answer  -> the written answer, delivered piece by piece

With GEMINI_API_KEY set, both use Google's Gemini API. Without a key the app
runs in demo mode: a simple keyword-based embedding and no written answer, so
the whole project can be tried before getting a key.
"""
import asyncio
import hashlib
import json
import re

import httpx
import numpy as np

from . import config

EMBED_DIM = 768
EMBED_BATCH = 50

SYSTEM_PROMPT = """You are an assistant that answers questions about the user's \
uploaded PDF documents.

Rules:
- Use only the numbered sources given with the question. Do not use outside knowledge.
- After each fact, cite the source number in square brackets, like [1] or [2].
- If the sources do not contain the answer, say that you could not find it in \
the documents. Do not guess.
- Be clear and concise. Use short paragraphs, bullet lists and code blocks when they help.
- Reply in the same language as the question."""


class AIError(Exception):
    """An AI problem with a message that is safe to show the user."""


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


# ---------------------------------------------------------------- demo mode

STOPWORDS = set(
    "a an and are as at be but by can do does for from give has have how i in is it "
    "me my of on or so that the their this to was what when where which who why "
    "will with you your".split()
)


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def demo_embed(texts: list[str]) -> np.ndarray:
    """Keyword embedding: each word adds weight to one of EMBED_DIM slots."""
    matrix = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in _words(text):
            slot = int(hashlib.md5(word.encode()).hexdigest(), 16) % EMBED_DIM
            matrix[row, slot] += 1.0
    return _normalize(matrix)


async def _demo_answer(sources: list[dict]):
    lines = [
        "**Demo mode.** No AI key is set, so this is a keyword search of your "
        "documents and not a written answer. Add a Gemini API key to the `.env` "
        "file to get real answers.",
        "",
        "Closest passages:",
        "",
    ]
    for number, source in enumerate(sources[:3], start=1):
        snippet = " ".join(source["text"].split())[:260]
        lines.append(f"- {snippet}... [{number}]")
    text = "\n".join(lines)
    for i in range(0, len(text), 24):
        yield text[i : i + 24]
        await asyncio.sleep(0.01)


# ------------------------------------------------------------------- Gemini

def _headers() -> dict:
    return {"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"}


def _error_message(status: int, body: str) -> str:
    try:
        detail = json.loads(body)["error"]["message"]
    except Exception:
        detail = body[:200]
    if status == 429:
        return "The free AI quota is used up for now. Wait a minute and try again."
    if status in (400, 401, 403) and "API key" in detail:
        return "The Gemini API key was rejected. Check GEMINI_API_KEY in the .env file."
    if status == 404:
        return (
            "The AI model name was not found. Check GEMINI_CHAT_MODEL and "
            "GEMINI_EMBED_MODEL in the .env file."
        )
    return f"The AI service returned an error ({status}): {detail}"


async def _gemini_embed(texts: list[str], task: str) -> np.ndarray:
    model = config.GEMINI_EMBED_MODEL
    url = f"{config.GEMINI_BASE_URL}/models/{model}:batchEmbedContents"
    vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=60) as client:
        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start : start + EMBED_BATCH]
            payload = {
                "requests": [
                    {
                        "model": f"models/{model}",
                        "content": {"parts": [{"text": text}]},
                        "taskType": task,
                        "outputDimensionality": EMBED_DIM,
                    }
                    for text in batch
                ]
            }
            for attempt in range(4):
                try:
                    response = await client.post(url, headers=_headers(), json=payload)
                except httpx.HTTPError as exc:
                    raise AIError("Could not reach the AI service. Check your internet.") from exc
                # The free tier allows a limited number of requests per minute,
                # so wait and retry a few times before giving up.
                if response.status_code == 429 and attempt < 3:
                    await asyncio.sleep(15)
                    continue
                break
            if response.status_code != 200:
                raise AIError(_error_message(response.status_code, response.text))
            vectors.extend(item["values"] for item in response.json()["embeddings"])
    return _normalize(np.array(vectors, dtype=np.float32))


async def _gemini_answer(question: str, history: list[dict], sources: list[dict]):
    context = "\n\n".join(
        f"[{n}] ({s['filename']}, page {s['page']})\n{s['text']}"
        for n, s in enumerate(sources, start=1)
    )
    contents = [
        {
            "role": "model" if message["role"] == "assistant" else "user",
            "parts": [{"text": message["content"]}],
        }
        for message in history
    ]
    contents.append(
        {"role": "user", "parts": [{"text": f"Sources:\n{context}\n\nQuestion: {question}"}]}
    )
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.2},
    }
    url = (
        f"{config.GEMINI_BASE_URL}/models/{config.GEMINI_CHAT_MODEL}"
        ":streamGenerateContent?alt=sse"
    )
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", url, headers=_headers(), json=payload) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise AIError(_error_message(response.status_code, body))
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    for candidate in event.get("candidates", []):
                        for part in candidate.get("content", {}).get("parts", []):
                            if part.get("text"):
                                yield part["text"]
    except httpx.HTTPError as exc:
        raise AIError("Could not reach the AI service. Check your internet.") from exc


# --------------------------------------------------------------- public API

async def embed(texts: list[str], for_query: bool = False) -> np.ndarray:
    if config.PROVIDER == "demo":
        return demo_embed(texts)
    task = "RETRIEVAL_QUERY" if for_query else "RETRIEVAL_DOCUMENT"
    return await _gemini_embed(texts, task)


def stream_answer(question: str, history: list[dict], sources: list[dict]):
    if config.PROVIDER == "demo":
        return _demo_answer(sources)
    return _gemini_answer(question, history, sources)
