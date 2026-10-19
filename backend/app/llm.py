"""Provider-agnostic LLM wrapper. Free options: Gemini (free tier), Groq (free tier),
Ollama (local, unlimited). `mock` works offline with no key."""
import json
import re
import time

import httpx

from .config import settings


class LLMError(RuntimeError):
    pass


def _post(url, *, headers=None, params=None, body=None, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            r = httpx.post(url, headers=headers, params=params, json=body, timeout=settings.llm_timeout)
            if r.status_code == 429 and attempt < retries:
                time.sleep(4 * (attempt + 1))  # free tiers rate-limit; back off and retry
                continue
            if r.status_code >= 400:
                raise LLMError(f"{settings.llm_provider} API error {r.status_code}: {r.text[:300]}")
            return r.json()
        except httpx.HTTPError as e:
            last = e
            if attempt < retries:
                time.sleep(2)
                continue
    raise LLMError(f"Could not reach {settings.llm_provider}: {last}")


def _gemini(prompt, system, temperature, json_mode):
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set. Add it to .env (free key: aistudio.google.com/apikey).")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    cfg = {"temperature": temperature}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    data = _post(
        url,
        headers={"x-goog-api-key": settings.gemini_api_key},
        body={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": cfg,
        },
    )
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError):
        raise LLMError(f"Unexpected Gemini response: {str(data)[:300]}")


def _groq(prompt, system, temperature, json_mode):
    if not settings.groq_api_key:
        raise LLMError("GROQ_API_KEY is not set. Add it to .env (free key: console.groq.com).")
    body = {
        "model": settings.groq_model,
        "temperature": temperature,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    data = _post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        body=body,
    )
    return data["choices"][0]["message"]["content"]


def _ollama(prompt, system, temperature, json_mode):
    body = {
        "model": settings.ollama_model,
        "stream": False,
        "options": {"temperature": temperature},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    if json_mode:
        body["format"] = "json"
    data = _post(f"{settings.ollama_url}/api/chat", body=body)
    return data["message"]["content"]


def _mock(prompt, system, temperature, json_mode):
    if json_mode:
        return "{}"
    return (
        "**[MOCK MODE]** No LLM is configured, so this is a placeholder response. "
        "Add `GEMINI_API_KEY` (free) or `GROQ_API_KEY` to `.env`, or run Ollama locally, "
        "then restart the server to get real analysis."
    )


_PROVIDERS = {"gemini": _gemini, "groq": _groq, "ollama": _ollama, "mock": _mock}


def generate(prompt: str, system: str = "You are an expert research assistant. Be accurate and concise.",
             temperature: float = 0.3, json_mode: bool = False) -> str:
    fn = _PROVIDERS.get(settings.llm_provider)
    if fn is None:
        raise LLMError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use gemini, groq, ollama or mock.")
    return fn(prompt, system, temperature, json_mode)


def extract_json(text: str):
    """Best-effort JSON extraction from an LLM reply. Returns None on failure."""
    if not text:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def generate_json(prompt: str, system: str = "You are an expert research assistant. Reply with valid JSON only."):
    return extract_json(generate(prompt, system=system, temperature=0.2, json_mode=True))
