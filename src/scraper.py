from __future__ import annotations

import os

import requests

from src.models import Article

DEFAULT_BASE_URL = "https://support.optisigns.com"
DEFAULT_LOCALE = "en-us"
DEFAULT_LIMIT = 50
PAGE_SIZE = 30


class Scraper:
    """Fetch published Help Center articles from the Zendesk API."""

    def __init__(
        self,
        base_url: str | None = None,
        locale: str | None = None,
        limit: int | None = None,
        page_size: int = PAGE_SIZE,
    ) -> None:
        self.base_url = (base_url or os.getenv("ZENDESK_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.locale = locale or os.getenv("ZENDESK_LOCALE", DEFAULT_LOCALE)
        self.limit = limit if limit is not None else int(os.getenv("ARTICLE_FETCH_LIMIT", DEFAULT_LIMIT))
        self.page_size = page_size

    def fetch(self) -> list[Article]:
        url: str | None = f"{self.base_url}/api/v2/help_center/{self.locale}/articles.json"
        params: dict[str, int] | None = {"per_page": self.page_size}
        articles: list[Article] = []
        seen_pages: set[str] = set()

        while url and len(articles) < self.limit:
            if url in seen_pages:
                break
            seen_pages.add(url)

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()

            for raw in payload.get("articles", []):
                if raw.get("draft"):
                    continue
                articles.append(_to_article(raw))
                if len(articles) >= self.limit:
                    break

            url = payload.get("next_page")
            params = None

        return articles


def _to_article(raw: dict) -> Article:
    return Article(
        id=int(raw["id"]),
        title=raw.get("title") or "",
        html=raw.get("body") or "",
        url=raw.get("html_url") or "",
        updated_at=raw.get("updated_at") or "",
    )
