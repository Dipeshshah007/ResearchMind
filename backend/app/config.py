"""Central configuration. Everything is driven by environment variables / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def _provider() -> str:
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    return "mock"  # runs fully offline so the UI can always be demoed


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.llm_provider = _provider()  # gemini | groq | ollama | mock
        self.llm_timeout = float(os.getenv("LLM_TIMEOUT", "90"))
        self.max_context_chars = int(os.getenv("MAX_CONTEXT_CHARS", "14000"))

        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2")

        self.s2_api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
        self.contact_email = os.getenv("CONTACT_EMAIL", "researchmind@example.com")
        self.max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "25"))
        self.feed_ttl = int(os.getenv("FEED_TTL_SECONDS", "300"))


settings = Settings()
