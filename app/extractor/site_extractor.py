import logging
import re
from urllib.parse import urlparse

import tldextract
from bs4 import BeautifulSoup

from app.models import ExternalSite

logger = logging.getLogger(__name__)

# Domains to always ignore — CDNs, tracking, social share widgets, etc.
IGNORE_DOMAINS = {
    "google.com",
    "googleapis.com",
    "gstatic.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "t.co",
    "bit.ly",
    "ow.ly",
    "tinyurl.com",
    "cloudflare.com",
    "cloudfront.net",
    "amazonaws.com",
    "wp.com",
    "wordpress.com",
    "gravatar.com",
    "addthis.com",
    "sharethis.com",
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
}

# Only look inside these content containers; fall back to whole page
CONTENT_SELECTORS = [
    "article",
    ".post-content",
    ".entry-content",
    ".article-body",
    ".post-body",
    "[class*='article-content']",
    "[class*='post-body']",
]


def _registered_domain(url: str) -> str:
    ext = tldextract.extract(url)
    return ext.registered_domain.lower()


def _is_ignorable(registered: str) -> bool:
    if not registered:
        return True
    # Check exact match or suffix match (e.g. sub.google.com)
    for ignore in IGNORE_DOMAINS:
        if registered == ignore or registered.endswith("." + ignore):
            return True
    return False


class SiteExtractor:
    """
    Given a list of (url, html) article pages and the seed domain,
    extract all unique external registered domains mentioned in them.
    """

    def extract(
        self,
        article_pages: list[tuple[str, str]],
        seed_domain: str,
    ) -> list[ExternalSite]:
        seed_registered = _registered_domain(seed_domain)
        seen: set[str] = set()
        results: list[ExternalSite] = []

        for page_url, html in article_pages:
            soup = BeautifulSoup(html, "lxml")

            # Prefer to look only inside article body
            scope = None
            for sel in CONTENT_SELECTORS:
                scope = soup.select_one(sel)
                if scope:
                    break
            scope = scope or soup  # fall back to full page

            for tag in scope.find_all("a", href=True):
                href = tag["href"].strip()

                # Skip non-http links
                if not href.startswith(("http://", "https://")):
                    continue

                registered = _registered_domain(href)

                # Skip seed domain (internal links that slipped through)
                if registered == seed_registered:
                    continue

                # Skip noise domains
                if _is_ignorable(registered):
                    continue

                # Dedup by (registered_domain, source_page)
                key = f"{registered}|{page_url}"
                if key in seen:
                    continue
                seen.add(key)

                results.append(
                    ExternalSite(
                        domain=registered,
                        source_url=page_url,
                        raw_url=href,
                    )
                )
                logger.debug(f"  External site: {registered}  ← {page_url}")

        logger.info(
            f"Extracted {len(results)} external site references "
            f"({len({r.domain for r in results})} unique domains)"
        )
        return results
