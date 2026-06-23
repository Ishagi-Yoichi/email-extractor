import logging
import re

from bs4 import BeautifulSoup

from app.config import settings

logger = logging.getLogger(__name__)

# ── URL signals ────────────────────────────────────────────────────────────────

BLOG_URL_PATTERNS = [
    r"/blog/",
    r"/news/",
    r"/post/",
    r"/posts/",
    r"/article/",
    r"/articles/",
    r"/story/",
    r"/stories/",
    r"/press/",
    r"/press-release/",
    r"/insights/",
    r"/resources/",
    r"/updates/",
    r"/editorial/",
    r"/\d{4}/\d{2}/\d{2}/",  # /2024/03/15/
    r"/\d{4}/\d{2}/[^/]+",  # /2024/03/some-slug
]

DROP_URL_PATTERNS = [
    r"/tag/",
    r"/tags/",
    r"/category/",
    r"/categories/",
    r"/author/",
    r"/page/\d+",
    r"/search",
    r"[?&]s=",
    r"/login",
    r"/signup",
    r"/register",
    r"/cart",
    r"/checkout",
    r"/product/",
    r"/shop/",
    r"/pricing",
    r"/about",
    r"/contact",
    r"/privacy",
    r"/terms",
    r"/#",
    r"\.pdf$",
    r"\.jpg$",
    r"\.png$",
    r"\.xml$",
]

# ── HTML structural signals ────────────────────────────────────────────────────

BYLINE_SELECTORS = [
    ".author",
    ".byline",
    ".post-author",
    ".entry-author",
    '[rel="author"]',
    '[class*="author"]',
    '[class*="byline"]',
]

CONTENT_SELECTORS = [
    "article",
    ".post-content",
    ".entry-content",
    ".article-body",
    ".post-body",
    "[class*='article']",
    "[class*='post-body']",
]


def score_url(url: str) -> int:
    """Score a URL based on path patterns. Returns points (can be negative)."""
    lower = url.lower()

    for pattern in DROP_URL_PATTERNS:
        if re.search(pattern, lower):
            return -100  # hard drop

    score = 0
    for pattern in BLOG_URL_PATTERNS:
        if re.search(pattern, lower):
            score += 10
    return score


def score_html(html: str, soup: BeautifulSoup) -> int:
    """Score based on HTML structural signals."""
    score = 0

    # Semantic article tag
    if soup.find("article"):
        score += 20

    # Datetime element (publish date)
    if soup.find("time"):
        score += 10

    # Author meta tag
    if soup.find("meta", {"name": "author"}):
        score += 10

    # Open Graph type = article
    og_type = soup.find("meta", {"property": "og:type"})
    if og_type and "article" in (og_type.get("content") or "").lower():
        score += 25

    # Schema.org markup
    if re.search(r'"@type"\s*:\s*"(Article|BlogPosting|NewsArticle)"', html):
        score += 25

    # Comment section (almost always an article)
    if soup.find(id=re.compile(r"comment", re.I)):
        score += 15
    if soup.find(class_=re.compile(r"comment", re.I)):
        score += 10

    return score


def score_content(soup: BeautifulSoup) -> int:
    """Score based on content heuristics."""
    score = 0

    body_text = soup.get_text(separator=" ", strip=True)
    word_count = len(body_text.split())

    if word_count > 600:
        score += 20
    elif word_count > 300:
        score += 10

    # Byline / author element
    if any(soup.select(sel) for sel in BYLINE_SELECTORS):
        score += 15

    # Reading-time estimate ("5 min read")
    if re.search(r"\d+\s*min(ute)?\s*read", body_text, re.I):
        score += 20

    # Outbound links inside content body
    content_el = None
    for sel in CONTENT_SELECTORS:
        content_el = soup.select_one(sel)
        if content_el:
            break

    if content_el:
        outbound = [
            a
            for a in content_el.find_all("a", href=True)
            if a["href"].startswith("http")
        ]
        if len(outbound) > 3:
            score += 10

    return score


class PageClassifier:
    """
    Multi-layer classifier that returns (is_article, score) for a page.

    Scoring:
      ≥ pass_threshold  → article (True)
      < drop_threshold  → not article (False)
      in between        → uncertain (returned as False for now; wire LLM here later)
    """

    def classify(self, url: str, html: str) -> tuple[bool, int]:
        url_pts = score_url(url)
        if url_pts == -100:
            return False, -100

        soup = BeautifulSoup(html, "lxml")
        total = url_pts + score_html(html, soup) + score_content(soup)

        logger.debug(f"Score {total:4d}  {url}")

        if total >= settings.classifier_pass_threshold:
            return True, total
        return False, total
