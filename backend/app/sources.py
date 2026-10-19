"""Live data connectors. All free / no-key APIs:
arXiv, OpenAlex (journals + conferences), Semantic Scholar, and RSS (blogs, Medium)."""
import html
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser
import httpx

from .config import settings

UA = {"User-Agent": f"ResearchMind/1.0 (mailto:{settings.contact_email})"}
VENUE_TYPES = ["Journal", "Conference", "Preprint", "Blog", "Article"]
SOURCES = {
    "all": "All sources",
    "arxiv": "arXiv (preprints)",
    "openalex": "OpenAlex (journals & conferences)",
    "semanticscholar": "Semantic Scholar",
    "blogs": "Blogs & Medium",
}
SORTS = {"relevance": "Most relevant", "newest": "Newest first", "citations": "Most cited"}
POPULAR_VENUES = [
    "NeurIPS", "ICML", "ICLR", "ACL", "EMNLP", "CVPR", "ICCV", "AAAI", "KDD",
    "Nature", "Science", "JMLR", "TPAMI", "arXiv", "Medium", "Towards Data Science",
    "Hugging Face", "Google", "OpenAI", "Distill", "BAIR",
]
RSS_FEEDS = [
    ("Google AI Blog", "https://blog.google/technology/ai/rss/", "Blog"),
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml", "Blog"),
    ("BAIR Blog", "https://bair.berkeley.edu/blog/feed.xml", "Blog"),
    ("OpenAI News", "https://openai.com/news/rss.xml", "Blog"),
    ("Distill", "https://distill.pub/rss.xml", "Blog"),
    ("Towards Data Science (Medium)", "https://towardsdatascience.com/feed", "Article"),
    ("Medium - Machine Learning", "https://medium.com/feed/tag/machine-learning", "Article"),
    ("Medium - LLM", "https://medium.com/feed/tag/llm", "Article"),
]
STOP = {"the", "and", "for", "with", "that", "from", "into", "about", "using", "what", "how", "are", "can"}

_cache: dict = {}


def _cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def _get(url, params=None, headers=None):
    r = httpx.get(url, params=params, headers={**UA, **(headers or {})}, timeout=20, follow_redirects=True)
    r.raise_for_status()
    return r


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _paper(**kw) -> dict:
    p = {"title": "", "authors": [], "published": "", "year": None, "venue": "", "venue_type": "Preprint",
         "abstract": "", "url": "", "pdf_url": "", "source": "", "citations": 0}
    p.update(kw)
    if not p["year"] and p["published"]:
        try:
            p["year"] = int(p["published"][:4])
        except ValueError:
            pass
    return p


# ---------------------------------------------------------------- arXiv
ARXIV = "https://export.arxiv.org/api/query"


def _parse_arxiv(text: str) -> list[dict]:
    out = []
    for e in feedparser.parse(text).entries:
        pdf = next((l.get("href", "") for l in e.get("links", []) if l.get("type") == "application/pdf"), "")
        out.append(_paper(title=_clean(e.get("title", "")), authors=[a.get("name", "") for a in e.get("authors", [])][:8],
                          published=e.get("published", ""), venue="arXiv", venue_type="Preprint",
                          abstract=_clean(e.get("summary", "")), url=e.get("link", ""), pdf_url=pdf, source="arXiv"))
    return out


def search_arxiv(q, limit=10, **_):
    terms = [t for t in re.findall(r"\w+", q) if t.lower() not in STOP] or [q]
    query = " AND ".join(f"all:{t}" for t in terms)
    r = _get(ARXIV, {"search_query": query, "max_results": limit, "sortBy": "relevance"})
    return _parse_arxiv(r.text)


def latest_arxiv(limit=15):
    cats = "cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CV"
    r = _get(ARXIV, {"search_query": cats, "max_results": limit, "sortBy": "submittedDate", "sortOrder": "descending"})
    return _parse_arxiv(r.text)


# ---------------------------------------------------------------- OpenAlex
_OA_TYPES = {"Journal": "journal", "Conference": "conference", "Preprint": "repository"}
_OA_BACK = {"journal": "Journal", "conference": "Conference", "repository": "Preprint"}


def _oa_abstract(inv) -> str:
    if not inv:
        return ""
    words = {}
    for w, positions in inv.items():
        for pos in positions:
            words[pos] = w
    return " ".join(words[i] for i in sorted(words))


def search_openalex(q, limit=10, year_from=None, year_to=None, venue_type=None, **_):
    flt = []
    if year_from:
        flt.append(f"from_publication_date:{year_from}-01-01")
    if year_to:
        flt.append(f"to_publication_date:{year_to}-12-31")
    if venue_type in _OA_TYPES:
        flt.append(f"primary_location.source.type:{_OA_TYPES[venue_type]}")
    params = {"search": q, "per-page": limit, "mailto": settings.contact_email}
    if flt:
        params["filter"] = ",".join(flt)
    out = []
    for w in _get("https://api.openalex.org/works", params).json().get("results", []):
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        out.append(_paper(
            title=w.get("title") or w.get("display_name") or "", published=w.get("publication_date") or "",
            year=w.get("publication_year"), authors=[a["author"]["display_name"] for a in w.get("authorships", [])][:8],
            venue=src.get("display_name") or "Unknown venue", venue_type=_OA_BACK.get(src.get("type"), "Journal"),
            abstract=_oa_abstract(w.get("abstract_inverted_index")), url=w.get("doi") or w.get("id", ""),
            pdf_url=loc.get("pdf_url") or "", source="OpenAlex", citations=w.get("cited_by_count") or 0))
    return out


# ---------------------------------------------------------------- Semantic Scholar
def search_semanticscholar(q, limit=10, year_from=None, year_to=None, **_):
    params = {"query": q, "limit": limit, "fields": "title,abstract,year,venue,authors,url,citationCount,publicationVenue,openAccessPdf,publicationDate"}
    if year_from or year_to:
        params["year"] = f"{year_from or ''}-{year_to or ''}"
    headers = {"x-api-key": settings.s2_api_key} if settings.s2_api_key else {}
    out = []
    for w in _get("https://api.semanticscholar.org/graph/v1/paper/search", params, headers).json().get("data", []):
        pv = w.get("publicationVenue") or {}
        vt = {"journal": "Journal", "conference": "Conference"}.get(pv.get("type"), "Preprint")
        venue = w.get("venue") or pv.get("name") or "Semantic Scholar"
        if "arxiv" in venue.lower():
            vt = "Preprint"
        out.append(_paper(title=w.get("title") or "", authors=[a.get("name", "") for a in w.get("authors", [])][:8],
                          published=w.get("publicationDate") or "", year=w.get("year"), venue=venue, venue_type=vt,
                          abstract=w.get("abstract") or "", url=w.get("url") or "",
                          pdf_url=(w.get("openAccessPdf") or {}).get("url", ""), source="Semantic Scholar",
                          citations=w.get("citationCount") or 0))
    return out


# ---------------------------------------------------------------- Blogs / Medium (RSS)
def _fetch_feed(name, url, vtype):
    try:
        feed = feedparser.parse(_get(url).text)
    except Exception:
        return []
    out = []
    for e in feed.entries[:25]:
        pp = e.get("published_parsed") or e.get("updated_parsed")
        published = datetime(*pp[:6], tzinfo=timezone.utc).isoformat() if pp else ""
        out.append(_paper(title=_clean(e.get("title", "")), authors=[e["author"]] if e.get("author") else [],
                          published=published, venue=name, venue_type=vtype,
                          abstract=_clean(e.get("summary", ""))[:1500], url=e.get("link", ""), source="RSS"))
    return out


def _all_feeds():
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = ex.map(lambda f: _fetch_feed(*f), RSS_FEEDS)
    return [p for r in results for p in r]


def search_blogs(q, limit=10, **_):
    items = _cached("rss_all", settings.feed_ttl, _all_feeds)
    terms = [t for t in re.findall(r"\w+", q.lower()) if t not in STOP]
    hits = [p for p in items if any(t in (p["title"] + " " + p["abstract"]).lower() for t in terms)] if terms else items
    return hits[: limit * 2]


# ---------------------------------------------------------------- aggregation
_FETCHERS = {"arxiv": search_arxiv, "openalex": search_openalex,
             "semanticscholar": search_semanticscholar, "blogs": search_blogs}


def _pick_sources(source, venue_type):
    if source and source != "all":
        return [source]
    if venue_type in ("Blog", "Article"):
        return ["blogs"]
    if venue_type == "Preprint":
        return ["arxiv", "openalex", "semanticscholar"]
    if venue_type in ("Journal", "Conference"):
        return ["openalex", "semanticscholar"]
    return list(_FETCHERS)


def _terms(q):
    return [t for t in re.findall(r"\w+", q.lower()) if t not in STOP and len(t) > 2]


def score(p, terms) -> float:
    t, a = p["title"].lower(), p["abstract"].lower()
    s = sum(3 for w in terms if w in t) + sum(1 for w in terms if w in a)
    return s + math.log1p(p.get("citations") or 0) * 0.5


def _norm(title):
    return re.sub(r"\W+", "", title.lower())


def search_all(query, year_from=None, year_to=None, venue_type=None, source="all", venue=None,
               limit=10, sort="relevance"):
    names = _pick_sources(source, venue_type)
    kwargs = dict(limit=limit, year_from=year_from, year_to=year_to, venue_type=venue_type)
    warnings = []

    def run(name):
        try:
            return _FETCHERS[name](query, **kwargs)
        except Exception as e:
            warnings.append(f"{SOURCES[name]} unavailable ({type(e).__name__})")
            return []

    with ThreadPoolExecutor(max_workers=4) as ex:
        batches = list(ex.map(run, names))

    seen, results = set(), []
    for p in (p for b in batches for p in b):
        key = _norm(p["title"])
        if not key or key in seen:
            continue
        seen.add(key)
        if year_from and p["year"] and p["year"] < year_from:
            continue
        if year_to and p["year"] and p["year"] > year_to:
            continue
        if venue_type and p["venue_type"] != venue_type:
            continue
        if venue and venue.lower() not in p["venue"].lower():
            continue
        results.append(p)

    terms = _terms(query)
    for p in results:
        p["score"] = round(score(p, terms), 2)
    if sort == "newest":
        results.sort(key=lambda p: p["published"] or str(p["year"] or ""), reverse=True)
    elif sort == "citations":
        results.sort(key=lambda p: p["citations"], reverse=True)
    else:
        results.sort(key=lambda p: p["score"], reverse=True)
    return results[: max(limit, 1) * 2], warnings


def live_feed(category="all", venue_type=None, limit=40):
    """Newest items across arXiv + blogs. Cached for FEED_TTL seconds; the UI polls it."""
    def build():
        items, warns = [], []
        for name, fn in (("arXiv", lambda: latest_arxiv(25)), ("RSS", lambda: _cached("rss_all", settings.feed_ttl, _all_feeds))):
            try:
                items += fn()
            except Exception as e:
                warns.append(f"{name} unavailable ({type(e).__name__})")
        items.sort(key=lambda p: p["published"] or "", reverse=True)
        return items, warns

    items, warns = _cached("feed", settings.feed_ttl, build)
    if category == "preprints":
        items = [p for p in items if p["source"] == "arXiv"]
    elif category == "blogs":
        items = [p for p in items if p["source"] == "RSS"]
    if venue_type:
        items = [p for p in items if p["venue_type"] == venue_type]
    return items[:limit], warns
