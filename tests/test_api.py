"""Offline tests: run with the mock LLM and a temp data dir (no network, no keys)."""
import os
import tempfile

os.environ["LLM_PROVIDER"] = "mock"
os.environ["DATA_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import sources  # noqa: E402
from backend.app.main import app  # noqa: E402

client = TestClient(app)


def test_health_and_filters():
    assert client.get("/api/health").json()["llm_provider"] == "mock"
    f = client.get("/api/filters").json()
    assert "Journal" in f["venue_types"] and f["years"][0] >= 2026


def test_paper_crud_versions_export():
    p = client.post("/api/papers", json={"title": "Test Paper", "year": 2024, "venue": "NeurIPS",
                                         "venue_type": "Conference", "content": "original text about transformers"}).json()
    pid = p["id"]
    assert client.get("/api/papers", params={"year": 2024, "venue_type": "Conference"}).json()[0]["id"] == pid
    upd = client.put(f"/api/papers/{pid}", json={"content": "edited text", "title": "Renamed"}).json()
    assert upd["title"] == "Renamed"
    versions = client.get(f"/api/papers/{pid}/versions").json()
    assert versions and versions[0]["content"] == "original text about transformers"
    assert "Renamed" in client.get(f"/api/papers/{pid}/export").text
    assert client.post(f"/api/papers/{pid}/review").status_code == 200
    assert "revised" in client.post(f"/api/papers/{pid}/ai-edit", json={"instruction": "fix grammar"}).json()
    assert client.delete(f"/api/papers/{pid}").status_code == 200
    assert client.get(f"/api/papers/{pid}").status_code == 404


def test_ask_without_papers_is_graceful():
    r = client.post("/api/ask", json={"question": "anything about zebras?"})
    assert r.status_code == 200 and "answer" in r.json()


def test_upload_rejects_non_pdf():
    r = client.post("/api/papers/upload", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_search_all_filters_and_dedupes(monkeypatch):
    mk = lambda t, y, vt: sources._paper(title=t, year=y, venue="V", venue_type=vt, abstract="graph neural networks", source="X")
    monkeypatch.setitem(sources._FETCHERS, "arxiv", lambda q, **k: [mk("Graph Nets", 2020, "Preprint"), mk("Old Paper", 2010, "Preprint")])
    monkeypatch.setitem(sources._FETCHERS, "openalex", lambda q, **k: [mk("graph nets", 2020, "Preprint")])
    res, _ = sources.search_all("graph neural", year_from=2015, source="all", venue_type="Preprint")
    assert [p["title"] for p in res] == ["Graph Nets"]


def test_llm_json_extraction():
    from backend.app.llm import extract_json
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json("noise {\"b\": 2} noise") == {"b": 2}
    assert extract_json("nothing") is None
