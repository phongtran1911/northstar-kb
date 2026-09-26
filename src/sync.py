from __future__ import annotations

import os

from src.cleaner import clean
from src.scraper import Scraper
from src.vector_store import VectorStore


def sync() -> int:
    """Scrape, clean, and upsert articles. Returns the number stored."""
    if not (os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")):
        raise RuntimeError("Set API_KEY in the environment or .env")

    used_slugs: set[str] = set()
    articles = [clean(article, used_slugs=used_slugs) for article in Scraper().fetch()]
    return VectorStore().upsert(articles)
