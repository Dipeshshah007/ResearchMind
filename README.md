# 🧠 ResearchMind — Autonomous AI Research Assistant Agent

An agentic AI web app that **discovers, reads, reviews, edits and answers questions about research**
peer-reviewed journals, conference papers, preprints, blogs and Medium articles with real-time updates.

| Feature | What it does |
|---|---|
| 🔎 **Discover** | One search across arXiv, OpenAlex (journals + conferences), Semantic Scholar, blogs & Medium. Dropdown filters: source, published-in type, journal/conference/medium, year range, sort. |
| ⚡ **Live Feed** | Newest AI/ML papers and blog posts, auto-refreshing every 60 s. |
| 🤖 **Research Agent** | Give a goal → Planner → Searcher → Ranker → Reader → Synthesizer → Critic produces a cited literature brief with a visible reasoning trace. |
| 📚 **Library + Editor** | Drag & drop PDFs, auto-detected metadata, edit everything, AI edit (select text → instruction → apply), version history with restore, export to Markdown. |
| 🧪 **AI Peer Review** | Reviewer agent returns strengths, weaknesses, novelty/rigor/clarity scores, recommendation, suggestions. |
| 💬 **Ask Your Papers** | RAG (ChromaDB) Q&A with numbered citations over your library. |

## 2. Step By Step: SetUp

1. **Create a virtual environment**
   ```bash
   python -m venv .venv
   ```
2. **Run the tests (optional but great for your repo):**
   ```bash
   pytest -q
   ```
3. **Start the app:**
   ```bash
   uvicorn backend.app.main:app --reload
   ```
