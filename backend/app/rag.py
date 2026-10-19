"""Retrieval-Augmented Generation over the user's library.
ChromaDB (local, free, built-in ONNX embeddings) with a keyword fallback so the app never hard-fails."""
import re

from . import db
from .config import settings

_col = None
_chroma_failed = False


def _collection():
    global _col, _chroma_failed
    if _chroma_failed:
        return None
    if _col is None:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(settings.data_dir / "chroma"))
            _col = client.get_or_create_collection("papers")
        except Exception:
            _chroma_failed = True
            return None
    return _col


def chunk(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


def delete_paper(pid: int) -> None:
    col = _collection()
    if col:
        try:
            col.delete(where={"paper_id": pid})
        except Exception:
            pass


def index_paper(pid: int, title: str, text: str) -> int:
    chunks = chunk(text)
    col = _collection()
    if not col or not chunks:
        return 0
    delete_paper(pid)
    try:
        col.add(ids=[f"{pid}:{i}" for i in range(len(chunks))], documents=chunks,
                metadatas=[{"paper_id": pid, "title": title, "chunk": i} for i in range(len(chunks))])
    except Exception:
        return 0
    return len(chunks)


def _keyword_retrieve(question: str, paper_ids, k: int):
    terms = {w for w in re.findall(r"\w+", question.lower()) if len(w) > 3}
    scored = []
    for p in db.list_papers():
        if paper_ids and p["id"] not in paper_ids:
            continue
        full = db.get_paper(p["id"])
        for i, ch in enumerate(chunk(full["content"] or full["abstract"])):
            s = sum(ch.lower().count(t) for t in terms)
            if s:
                scored.append((s, {"paper_id": p["id"], "title": p["title"], "chunk": i, "text": ch}))
    scored.sort(key=lambda x: -x[0])
    return [x[1] for x in scored[:k]]


def retrieve(question: str, paper_ids=None, k: int = 5) -> list[dict]:
    col = _collection()
    if col:
        try:
            where = {"paper_id": {"$in": list(paper_ids)}} if paper_ids else None
            res = col.query(query_texts=[question], n_results=k, where=where)
            docs, metas = res["documents"][0], res["metadatas"][0]
            if docs:
                return [{"paper_id": m["paper_id"], "title": m["title"], "chunk": m["chunk"], "text": d}
                        for d, m in zip(docs, metas)]
        except Exception:
            pass
    return _keyword_retrieve(question, paper_ids, k)
