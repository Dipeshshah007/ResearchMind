"""PDF ingestion: text extraction + metadata detection (LLM-assisted with heuristic fallback)."""
import io
import re
from datetime import date

from pypdf import PdfReader

from . import llm


def extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n\n".join(pages).strip()


def _heuristic(text: str, filename: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 8]
    title = lines[0][:200] if lines else filename.rsplit(".", 1)[0]
    years = [int(y) for y in re.findall(r"\b(19[89]\d|20[0-4]\d)\b", text[:3000]) if int(y) <= date.today().year]
    abstract = ""
    m = re.search(r"abstract[\s:.\-—]*(.{200,1800}?)(?:\n\s*\n|1\.?\s+introduction)", text[:8000], re.I | re.S)
    if m:
        abstract = re.sub(r"\s+", " ", m.group(1)).strip()
    return {"title": title, "authors": "", "year": max(years) if years else None,
            "venue": "", "venue_type": "Preprint", "abstract": abstract}


def extract_metadata(text: str, filename: str) -> dict:
    meta = _heuristic(text, filename)
    try:
        data = llm.generate_json(
            "Extract bibliographic metadata from the start of this paper. Reply as JSON with keys: "
            "title, authors (comma separated string), year (integer or null), venue (journal/conference/site or ''), "
            "venue_type (one of Journal, Conference, Preprint, Blog, Article), abstract (string).\n\n"
            f"PAPER START:\n{text[:3500]}")
        if isinstance(data, dict):
            for k in ("title", "authors", "venue", "abstract"):
                if isinstance(data.get(k), str) and data[k].strip():
                    meta[k] = data[k].strip()
            if isinstance(data.get("year"), int):
                meta["year"] = data["year"]
            if data.get("venue_type") in ("Journal", "Conference", "Preprint", "Blog", "Article"):
                meta["venue_type"] = data["venue_type"]
    except llm.LLMError:
        pass  # heuristics are good enough; the user can edit metadata in the UI
    return meta
