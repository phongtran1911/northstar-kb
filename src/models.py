from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Article:
    id: int
    title: str
    html: str
    url: str
    markdown: str = ""
