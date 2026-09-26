from __future__ import annotations

import os

from src.cleaner import clean
from src.scraper import Scraper
from src.vector_store import VectorStore


def sync() -> None:
    """Scrape help-center articles, write Markdown, and upload what changed."""
    if not (os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")):
        raise RuntimeError("Set API_KEY in the environment or .env")

    used_slugs: set[str] = set()
    for article in Scraper().fetch():
        clean(article, used_slugs=used_slugs)
    VectorStore().upsert()
