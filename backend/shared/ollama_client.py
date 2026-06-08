"""
Ollama client for embeddings and LLM completions.
Uses the local Ollama server (http://localhost:11434 by default).

Models required:
  - nomic-embed-text  (768-dim embeddings)
  - llama3            (general-purpose LLM for alert agent)

Pull them once:
  ollama pull nomic-embed-text
  ollama pull llama3
"""
from __future__ import annotations

import os

import httpx
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.llms import Ollama

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "llama3")


# ---------------------------------------------------------------------------
# LangChain wrappers
# ---------------------------------------------------------------------------

def get_embeddings() -> OllamaEmbeddings:
    """Return a LangChain OllamaEmbeddings instance."""
    return OllamaEmbeddings(
        base_url=OLLAMA_BASE_URL,
        model=EMBED_MODEL,
    )


def get_llm(temperature: float = 0.0) -> Ollama:
    """Return a LangChain Ollama LLM instance."""
    return Ollama(
        base_url=OLLAMA_BASE_URL,
        model=LLM_MODEL,
        temperature=temperature,
    )


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def embed_text(text: str) -> list[float]:
    """Embed a single text string and return the vector."""
    embeddings = get_embeddings()
    return embeddings.embed_query(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts and return list of vectors."""
    embeddings = get_embeddings()
    return embeddings.embed_documents(texts)


def ollama_available() -> bool:
    """Check whether the local Ollama server is running."""
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        return resp.status_code == 200
    except httpx.ConnectError:
        return False
