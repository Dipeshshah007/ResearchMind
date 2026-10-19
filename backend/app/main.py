"""ResearchMind API. Run: uvicorn backend.app.main:app --reload"""
from datetime import date
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agents, db, ingest, llm, rag, sources
from .config import BASE_DIR, settings

FRONTEND = BASE_DIR / "frontend"

app = FastAPI(title="ResearchMind", version="1.0.0", description="Autonomous AI research assistant")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
db.init()


@app.exception_handler(llm.LLMError)
async def llm_error_handler(_, exc: llm.LLMError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


# ------------------------------------------------------------------ models
class SearchReq(BaseModel):
    query: str
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    venue_type: Optional[str] = None
    source: str = "all"
    venue: Optional[str] = None
    sort: str = "relevance"
    limit: int = 10


class AgentReq(BaseModel):
    goal: str
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    venue_type: Optional[str] = None
    source: str = "all"
    depth: int = 5


class PaperIn(BaseModel):
    title: str
    authors: str = ""
    year: Optional[int] = None
    venue: str = ""
    venue_type: str = "Other"
    abstract: str = ""
    url: str = ""
    source: str = "search"
    content: str = ""
    notes: str = ""


class PaperUpdate(BaseModel):
    title: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    venue_type: Optional[str] = None
    abstract: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    content: Optional[str] = None


class EditReq(BaseModel):
    instruction: str
    selection: Optional[str] = None


class AskReq(BaseModel):
    question: str
    paper_ids: Optional[list[int]] = None


def _need(pid: int) -> dict:
    p = db.get_paper(pid)
    if not p:
        raise HTTPException(404, "Paper not found")
    return p


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health():
    return {"status": "ok", "llm_provider": settings.llm_provider,
            "llm_model": {"gemini": settings.gemini_model, "groq": settings.groq_model,
                          "ollama": settings.ollama_model}.get(settings.llm_provider, "none")}


@app.get("/api/filters")
def filters():
    this_year = date.today().year
    return {"years": list(range(this_year, 1999, -1)), "venue_types": sources.VENUE_TYPES,
            "sources": [{"value": k, "label": v} for k, v in sources.SOURCES.items()],
            "sorts": [{"value": k, "label": v} for k, v in sources.SORTS.items()],
            "venues": sources.POPULAR_VENUES}


# ------------------------------------------------------------------ discovery
@app.post("/api/search")
def search(req: SearchReq):
    if not req.query.strip():
        raise HTTPException(400, "Query is empty")
    results, warnings = sources.search_all(req.query, req.year_from, req.year_to, req.venue_type,
                                           req.source, req.venue, min(req.limit, 25), req.sort)
    return {"results": results, "warnings": warnings}


@app.get("/api/feed")
def feed(category: str = "all", venue_type: Optional[str] = None, limit: int = 40):
    items, warnings = sources.live_feed(category, venue_type or None, limit)
    return {"items": items, "warnings": warnings, "ttl": settings.feed_ttl}


@app.post("/api/agent/run")
def agent_run(req: AgentReq):
    if not req.goal.strip():
        raise HTTPException(400, "Goal is empty")
    return agents.run_research(req.goal, req.year_from, req.year_to, req.venue_type, req.source, req.depth)


# ------------------------------------------------------------------ library
@app.get("/api/papers")
def papers(year: Optional[int] = None, venue_type: Optional[str] = None, q: Optional[str] = None,
           source: Optional[str] = None):
    return db.list_papers(year, venue_type or None, q or None, source or None)


@app.post("/api/papers")
def create_paper(p: PaperIn):
    d = p.model_dump()
    d["content"] = d["content"] or d["abstract"]
    pid = db.add_paper(d)
    rag.index_paper(pid, d["title"], d["content"])
    return db.get_paper(pid)


@app.post("/api/papers/upload")
def upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")
    data = file.file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")
    try:
        text = ingest.extract_pdf_text(data)
    except Exception as e:
        raise HTTPException(422, f"Could not read PDF: {e}")
    if not text.strip():
        raise HTTPException(422, "No extractable text (scanned PDF?). Try an OCR'd copy.")
    meta = ingest.extract_metadata(text, file.filename)
    pid = db.add_paper({**meta, "content": text, "source": "upload"})
    rag.index_paper(pid, meta["title"], text)
    return db.get_paper(pid)


@app.get("/api/papers/{pid}")
def get_paper(pid: int):
    return _need(pid)


@app.put("/api/papers/{pid}")
def update_paper(pid: int, upd: PaperUpdate):
    old = _need(pid)
    new = db.update_paper(pid, upd.model_dump(exclude_none=True))
    if upd.content is not None and upd.content != old["content"]:
        rag.index_paper(pid, new["title"], new["content"])
    return new


@app.delete("/api/papers/{pid}")
def delete_paper(pid: int):
    _need(pid)
    rag.delete_paper(pid)
    db.delete_paper(pid)
    return {"deleted": pid}


@app.get("/api/papers/{pid}/versions")
def versions(pid: int):
    _need(pid)
    return db.list_versions(pid)


@app.get("/api/papers/{pid}/export")
def export(pid: int):
    p = _need(pid)
    md = (f"# {p['title']}\n\n**Authors:** {p['authors']}  \n**Year:** {p['year']}  \n"
          f"**Venue:** {p['venue']} ({p['venue_type']})\n\n## Abstract\n{p['abstract']}\n\n## Full text\n{p['content']}\n")
    if p["notes"]:
        md += f"\n## Notes\n{p['notes']}\n"
    return PlainTextResponse(md, headers={"Content-Disposition": f'attachment; filename="paper-{pid}.md"'})


# ------------------------------------------------------------------ AI actions on a paper
@app.post("/api/papers/{pid}/review")
def review(pid: int):
    return agents.review_paper(_need(pid))


@app.post("/api/papers/{pid}/summarize")
def summarize(pid: int):
    return {"summary": agents.summarize(_need(pid))}


@app.post("/api/papers/{pid}/ai-edit")
def ai_edit(pid: int, req: EditReq):
    p = _need(pid)
    text = req.selection if req.selection else p["content"]
    return {"revised": agents.ai_edit(req.instruction, text, p["title"]), "scope": "selection" if req.selection else "document"}


@app.post("/api/ask")
def ask(req: AskReq):
    if not req.question.strip():
        raise HTTPException(400, "Question is empty")
    return agents.ask_library(req.question, req.paper_ids)


# ------------------------------------------------------------------ frontend
app.mount("/static", StaticFiles(directory=FRONTEND / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
