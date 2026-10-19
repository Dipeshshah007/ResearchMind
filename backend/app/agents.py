"""Multi-agent orchestration.

Pipeline for a research goal:
  Planner -> Searcher -> Ranker -> Reader -> Synthesizer -> Critic
Each step is logged to a trace that the UI renders, so the agent's reasoning is transparent.
Single-purpose agents (Reviewer, Editor, Q&A) share the same LLM layer."""
import time

from . import llm, rag, sources
from .config import settings


def _clip(text: str, n: int | None = None) -> str:
    n = n or settings.max_context_chars
    return text if len(text) <= n else text[:n] + "\n...[truncated]"


class Trace:
    def __init__(self):
        self.t0 = time.time()
        self.steps: list[dict] = []

    def log(self, agent: str, action: str, detail: str = ""):
        self.steps.append({"agent": agent, "action": action, "detail": detail, "t": round(time.time() - self.t0, 1)})


def run_research(goal: str, year_from=None, year_to=None, venue_type=None, source="all", depth: int = 5) -> dict:
    tr = Trace()
    depth = max(3, min(depth, 8))

    # 1. Planner
    plan = llm.generate_json(
        "You plan literature searches. Given the research goal, propose 3 distinct, short search queries "
        '(2-6 words each) that together cover it. Reply as JSON: {"queries": ["..."], "angle": "one sentence"}.\n'
        f"GOAL: {goal}")
    queries = [q for q in (plan or {}).get("queries", []) if isinstance(q, str) and q.strip()][:3] or [goal]
    tr.log("Planner", "Decomposed goal into search queries", " | ".join(queries))

    # 2. Searcher
    pool, warnings = {}, []
    for q in queries:
        found, warns = sources.search_all(q, year_from, year_to, venue_type, source, limit=8)
        warnings += warns
        for p in found:
            pool.setdefault(sources._norm(p["title"]), p)
        tr.log("Searcher", f"Searched '{q}'", f"{len(found)} results")
    for w in set(warnings):
        tr.log("Searcher", "Warning", w)

    # 3. Ranker
    terms = sources._terms(goal + " " + " ".join(queries))
    ranked = sorted(pool.values(), key=lambda p: sources.score(p, terms), reverse=True)
    top = [p for p in ranked if p["abstract"]][:depth] or ranked[:depth]
    tr.log("Ranker", "Selected most relevant papers", f"{len(top)} of {len(pool)} unique candidates")
    if not top:
        return {"report": "No papers matched. Try broader keywords or relax the filters.", "papers": [],
                "trace": tr.steps, "queries": queries}

    listing = "\n\n".join(
        f"[{i}] {p['title']} ({p['year']}, {p['venue']})\nAbstract: {_clip(p['abstract'], 900)}"
        for i, p in enumerate(top, 1))

    # 4. Reader
    notes = llm.generate(
        "For each numbered paper, write 2 bullet points: the core contribution and the key limitation/assumption. "
        "Use only the provided abstract; do not invent details. Keep the [n] labels.\n\n" + listing,
        temperature=0.2)
    tr.log("Reader", "Extracted contributions and limitations", f"{len(top)} abstracts read")

    # 5. Synthesizer
    report = llm.generate(
        f"Research goal: {goal}\n\nReader notes:\n{notes}\n\nSources:\n{listing}\n\n"
        "Write a literature brief in Markdown with these sections: ## TL;DR, ## Key Findings, "
        "## Methods Landscape, ## Gaps & Open Problems, ## Suggested Next Steps. "
        "Cite sources inline as [1], [2] using ONLY the numbers above. Never cite a number that does not exist. "
        "Do not claim anything the abstracts do not support.", temperature=0.35)
    tr.log("Synthesizer", "Drafted literature brief", f"{len(report)} characters")

    # 6. Critic (self-verification pass)
    critique = llm.generate(
        "You are a strict fact-checker. Compare the REPORT with the SOURCES. List up to 4 bullets of claims that "
        "look unsupported, overstated, or mis-cited, then one line on overall confidence (High/Medium/Low). "
        "If all is fine say so.\n\nREPORT:\n" + _clip(report, 6000) + "\n\nSOURCES:\n" + listing, temperature=0.1)
    tr.log("Critic", "Verified claims against sources")
    report += "\n\n## Verification Notes\n" + critique

    return {"report": report, "papers": top, "trace": tr.steps, "queries": queries}


def review_paper(paper: dict) -> dict:
    body = _clip(paper.get("content") or paper.get("abstract") or "")
    data = llm.generate_json(
        "Act as a rigorous peer reviewer (NeurIPS/ICML style). Review the paper below. Reply as JSON with keys: "
        "summary (string), strengths (array of strings), weaknesses (array of strings), "
        "novelty (1-10), rigor (1-10), clarity (1-10), "
        "recommendation (Accept | Weak Accept | Borderline | Weak Reject | Reject), "
        "suggestions (array of concrete improvements).\n\n"
        f"TITLE: {paper.get('title')}\n\nTEXT:\n{body}")
    if isinstance(data, dict) and data.get("summary"):
        return data
    return {"summary": llm.generate("Write a short peer review of this paper:\n" + body),
            "strengths": [], "weaknesses": [], "suggestions": []}


def ai_edit(instruction: str, text: str, title: str = "") -> str:
    return llm.generate(
        "You are an expert academic editor. Apply the instruction to the text. Preserve meaning, citations, "
        "equations and technical terms. Return ONLY the revised text, with no commentary.\n\n"
        f"PAPER: {title}\nINSTRUCTION: {instruction}\n\nTEXT:\n{_clip(text)}", temperature=0.4)


def summarize(paper: dict) -> str:
    return llm.generate(
        "Summarize this paper for a busy researcher: 1 sentence TL;DR, then bullets for problem, method, "
        "results, limitations.\n\n" + _clip(paper.get("content") or paper.get("abstract") or ""))


def ask_library(question: str, paper_ids=None) -> dict:
    hits = rag.retrieve(question, paper_ids, k=5)
    if not hits:
        return {"answer": "I couldn't find relevant passages. Upload or save papers to your Library first.", "sources": []}
    ctx = "\n\n".join(f"[{i}] ({h['title']})\n{h['text']}" for i, h in enumerate(hits, 1))
    answer = llm.generate(
        "Answer the question using ONLY the context passages. Cite passages as [1], [2]. "
        "If the context is insufficient, say so.\n\n"
        f"CONTEXT:\n{ctx}\n\nQUESTION: {question}")
    return {"answer": answer, "sources": [{"n": i, "paper_id": h["paper_id"], "title": h["title"], "snippet": h["text"][:300]}
                                           for i, h in enumerate(hits, 1)]}
