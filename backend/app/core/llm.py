"""Optional LLM access.

The pipeline is fully deterministic without any LLM. When a provider key is
configured (OPENAI_API_KEY / GROQ_API_KEY / GOOGLE_API_KEY), the research and
report agents may use it for narrative text only — never for math.
"""
from __future__ import annotations

import logging
import threading

from ..core.config import settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_cached = None
_resolved = False


def get_llm():
    """Return a LangChain chat model or None. Never raises."""
    global _cached, _resolved
    with _lock:
        if _resolved:
            return _cached
        _resolved = True
        provider = (settings.llm_provider or "auto").lower()
        try:
            if provider in ("auto", "openai") and settings.openai_api_key:
                from langchain_openai import ChatOpenAI
                _cached = ChatOpenAI(
                    api_key=settings.openai_api_key,
                    model=settings.llm_model or "gpt-4o-mini", temperature=0.2,
                )
                logger.info("LLM provider: openai")
            elif provider in ("auto", "groq") and settings.groq_api_key:
                from langchain_groq import ChatGroq
                _cached = ChatGroq(api_key=settings.groq_api_key,
                                   model=settings.llm_model or "llama-3.3-70b-versatile")
                logger.info("LLM provider: groq")
            elif provider in ("auto", "google") and settings.google_api_key:
                from langchain_google_genai import ChatGoogleGenerativeAI
                _cached = ChatGoogleGenerativeAI(
                    api_key=settings.google_api_key,
                    model=settings.llm_model or "gemini-2.0-flash")
                logger.info("LLM provider: google")
            else:
                _cached = None
                logger.info("LLM disabled — deterministic pipeline only")
        except Exception as exc:  # noqa: BLE001 — LLM is optional enrichment
            logger.warning("LLM init failed (%s); continuing deterministically", exc)
            _cached = None
        return _cached


def llm_complete(system: str, user: str, *, max_tokens: int = 700) -> tuple[str, bool]:
    """Returns (text, llm_used). On any failure returns ('', False)."""
    model = get_llm()
    if model is None:
        return "", False
    try:
        resp = model.invoke(
            [system_instruction(system), human_message(user)],
            config={"max_tokens": max_tokens},
        )
        text = getattr(resp, "content", "") or ""
        return (text.strip(), True) if text.strip() else ("", False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM call failed (%s); falling back to deterministic text", exc)
        return "", False


def system_instruction(text: str):
    from langchain_core.messages import SystemMessage
    return SystemMessage(content=text)


def human_message(text: str):
    from langchain_core.messages import HumanMessage
    return HumanMessage(content=text)
