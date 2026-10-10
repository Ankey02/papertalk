"""Read a PDF and cut its text into overlapping chunks, keeping page numbers."""
import re
from pathlib import Path

from pypdf import PdfReader

from . import config


class IngestError(Exception):
    """A problem with the uploaded file that the user should be told about."""


def extract_pages(path: Path) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] for pages that contain text."""
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise IngestError("This PDF is password protected.")
        total = len(reader.pages)
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError("This file could not be read as a PDF.") from exc

    if total > config.MAX_PAGES:
        raise IngestError(
            f"This PDF has {total} pages. The limit is {config.MAX_PAGES}."
        )

    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            pages.append((number, text))

    if not pages:
        raise IngestError(
            "No text was found in this PDF. It may be a scanned document."
        )
    return pages


def split_text(text: str, size: int, overlap: int) -> list[str]:
    """Split text into pieces of about `size` characters, ending at a sentence
    or line break when one is nearby, with `overlap` characters repeated."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind(". "), window.rfind("? "))
            if cut > size * 0.5:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def chunk_pages(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Return [(page_number, chunk_text), ...] for the whole document."""
    result = []
    for number, text in pages:
        for piece in split_text(text, config.CHUNK_SIZE, config.CHUNK_OVERLAP):
            result.append((number, piece))
    return result
