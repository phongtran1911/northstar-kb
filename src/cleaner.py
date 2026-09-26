from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Comment, Tag
from markdownify import markdownify

from src.models import Article

UNWANTED_TAGS = (
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "noscript",
    "iframe",
    "svg",
    "form",
    "button",
    "aside",
)
FOOTER_HEADINGS = {
    "related articles",
    "related article",
    "see also",
    "that's all",
    "that's all!",
    "that’s all",
    "that’s all!",
}
USELESS_IMAGE_ALTS = {
    "",
    "image",
    "img",
    "icon",
    "photo",
    "picture",
    "screenshot",
    "spacer",
    "blank",
}


def clean(
    article: Article,
    dest: Path | None = None,
    used_slugs: set[str] | None = None,
) -> Article:
    """Turn article HTML into Markdown and write ``article-slug.md``."""
    html = _prepare_html(article.html, article.url)
    body = _html_to_markdown(html)
    article.markdown = _render_document(article.title, body, article.url)
    _save(article, dest or _articles_dir(), used_slugs)
    return article


def _articles_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data/articles"))


def _prepare_html(html: str, article_url: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.body or soup
    _remove_unwanted(soup, root)
    _normalize_links(root, article_url)
    return root.decode_contents()


def _remove_unwanted(soup: BeautifulSoup, root: Tag) -> None:
    for comment in root.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()

    for tag in root.find_all(UNWANTED_TAGS):
        tag.decompose()

    _remove_anchor_menus(root)
    _remove_footer_sections(root)
    _promote_intro(soup, root)
    _callouts_to_blockquotes(soup, root)
    _unwrap(root, ("figure", "span", "font"))
    _drop_useless_images(root)

    for tag in root.find_all("hr"):
        tag.decompose()

    for tag in root.find_all("a"):
        if not (tag.get("href") or "").strip() and not tag.get_text(strip=True):
            tag.decompose()


def _remove_anchor_menus(root: Tag) -> None:
    """Drop in-page tables of contents. They repeat the article headings."""
    menus: list[Tag] = []
    for listing in root.find_all(["ul", "ol"]):
        if listing.find_parent(["ul", "ol"]):
            continue
        links = listing.find_all("a")
        if not links:
            continue
        if all((link.get("href") or "").startswith("#") for link in links):
            menus.append(listing)
    for listing in menus:
        listing.decompose()


def _remove_footer_sections(root: Tag) -> None:
    headings = [
        heading
        for heading in root.find_all(re.compile(r"^h[1-6]$"))
        if _heading_text(heading) in FOOTER_HEADINGS
    ]
    if not headings:
        return
    heading = headings[0]
    for sibling in list(heading.find_next_siblings()):
        sibling.decompose()
    heading.decompose()


def _promote_intro(soup: BeautifulSoup, root: Tag) -> None:
    for heading in root.find_all(re.compile(r"^h[1-6]$")):
        if not _heading_text(heading).lower().startswith("in this article"):
            continue
        paragraph = soup.new_tag("p")
        paragraph.extend(list(heading.contents))
        heading.replace_with(paragraph)
        break


def _callouts_to_blockquotes(soup: BeautifulSoup, root: Tag) -> None:
    for table in list(root.find_all("table")):
        rows = table.find_all("tr")
        if not rows or any(len(row.find_all(["td", "th"], recursive=False)) != 1 for row in rows):
            continue
        quote = soup.new_tag("blockquote")
        for row in rows:
            cell = row.find(["td", "th"])
            if cell is None:
                continue
            for child in list(cell.contents):
                quote.append(child)
        table.replace_with(quote)


def _drop_useless_images(root: Tag) -> None:
    for image in list(root.find_all("img")):
        if _image_is_useful(image):
            alt = re.sub(r"\s+", " ", image.get("alt") or "").strip()
            image.attrs = {"src": image.get("src") or "", "alt": alt}
            continue
        image.decompose()


def _image_is_useful(image: Tag) -> bool:
    src = (image.get("src") or "").strip()
    if not src or src.startswith("data:"):
        return False
    alt = re.sub(r"\s+", " ", image.get("alt") or "").strip().lower()
    if alt in USELESS_IMAGE_ALTS:
        return False
    width = _positive_int(image.get("width"))
    height = _positive_int(image.get("height"))
    if (width is not None and width <= 8) or (height is not None and height <= 8):
        return False
    return True


def _normalize_links(root: Tag, article_url: str) -> None:
    base = article_url or "https://support.optisigns.com/"
    for link in root.find_all("a"):
        href = (link.get("href") or "").strip()
        if not href or href.lower().startswith("javascript:"):
            link.unwrap()
            continue
        if href.startswith("#"):
            link["href"] = urljoin(base, href)
        elif not href.startswith(("mailto:", "tel:")):
            link["href"] = _without_tracking(urljoin(base, href))
        allowed = {"href": link["href"]}
        if link.get("title"):
            allowed["title"] = link["title"]
        link.attrs = allowed

    for image in root.find_all("img"):
        src = (image.get("src") or "").strip()
        if src:
            image["src"] = urljoin(base, src)


def _html_to_markdown(html: str) -> str:
    rendered = markdownify(
        html,
        heading_style="atx",
        bullets="-",
        escape_misc=False,
        keep_inline_images_in=["p", "td", "th", "li", "figure", "blockquote"],
        code_language_callback=_code_language,
    )
    return _tidy(rendered)


def _render_document(title: str, body: str, url: str) -> str:
    heading = title.strip() or "Untitled"
    parts = [f"# {heading}"]
    if body:
        parts.extend(["", body])
    if url:
        parts.extend(["", f"Article URL: {url.strip()}"])
    return "\n".join(parts).rstrip() + "\n"


def _save(article: Article, dest: Path, used_slugs: set[str] | None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    slug = _unique_slug(article.title, article.id, used_slugs)
    path = dest / f"{slug}.md"
    path.write_text(article.markdown, encoding="utf-8")


def _unique_slug(title: str, article_id: int, used_slugs: set[str] | None) -> str:
    base = _slugify(title) or f"article-{article_id}"
    slug = base
    if used_slugs is not None and slug in used_slugs:
        slug = f"{base}-{article_id}"
    if used_slugs is not None:
        used_slugs.add(slug)
    return slug


def _slugify(title: str) -> str:
    text = unicodedata.normalize("NFKD", title)
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _heading_text(heading: Tag) -> str:
    return re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip().lower()


def _unwrap(root: Tag, names: tuple[str, ...]) -> None:
    for tag in list(root.find_all(names)):
        tag.unwrap()


def _code_language(element: Tag) -> str:
    code = element.find("code")
    classes = []
    if isinstance(code, Tag):
        classes.extend(code.get("class") or [])
    classes.extend(element.get("class") or [])
    for name in classes:
        if name.startswith("language-") and name != "language-auto":
            return name[len("language-") :]
    return ""


def _without_tracking(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.query:
        return url
    kept = [
        part
        for part in parsed.query.split("&")
        if part and not part.split("=", 1)[0].lower().startswith("utm_")
    ]
    return urlunparse(parsed._replace(query="&".join(kept)))


def _positive_int(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    return int(match.group())


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
