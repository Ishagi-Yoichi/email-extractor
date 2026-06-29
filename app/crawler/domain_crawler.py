import asyncio
import logging
from collections import deque
from urllib.parse import urljoin, urlparse

import httpx
import tldextract
from bs4 import BeautifulSoup

from app.config import settings
from app.crawler.robots import RobotsChecker

logger = logging.getLogger(__name__)


def normalise_url(url: str) -> str:
    """Strip fragments and trailing slashes for dedup."""
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl().rstrip("/")


def same_registered_domain(url: str, seed: str) -> bool:
    """True if url belongs to the same registered domain as seed."""
    return (
        tldextract.extract(url).registered_domain
        == tldextract.extract(seed).registered_domain
    )


class DomainCrawler:
    """
    Async BFS crawler limited to the seed domain.

    Returns a list of (url, html) tuples for every successfully
    fetched page, up to max_pages_per_domain.
    """

    def __init__(self):
        self.robots = RobotsChecker(user_agent=settings.user_agent)
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_requests)
        self.headers = {"User-Agent": settings.user_agent}

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> str | None:
        """Fetch a single URL. Returns HTML string or None on failure."""
        async with self.semaphore:
            try:
                resp = await client.get(
                    url,
                    headers=self.headers,
                    timeout=settings.request_timeout_seconds,
                    follow_redirects=True,
                )
                content_type = resp.headers.get("content-type", "")
                if resp.status_code == 200 and "text/html" in content_type:
                    return resp.text
            except Exception as e:
                logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def _extract_links(self, html: str, base_url: str) -> list[str]:
        """Pull all href links from a page and resolve to absolute URLs."""
        soup = BeautifulSoup(html, "lxml")
        links = []
        for tag in soup.find_all("a", href=True):
            href = str(tag["href"]).strip()
            if href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            absolute = urljoin(base_url, href)
            # Only http/https
            if urlparse(absolute).scheme in ("http", "https"):
                links.append(normalise_url(absolute))
        return links

    async def crawl(self, seed_url: str) -> list[tuple[str, str]]:
        """
        BFS crawl of seed_url domain.
        Returns list of (url, html) for all fetched pages.
        """
        if not seed_url.startswith(("http://", "https://")):
            seed_url = "https://" + seed_url

        seed_url = normalise_url(seed_url)
        visited: set[str] = set()
        queue: deque[str] = deque([seed_url])
        results: list[tuple[str, str]] = []

        # Also try the sitemap to seed the queue quickly
        sitemap_urls = await self._try_sitemap(seed_url)
        queue.extendleft(sitemap_urls)

        async with httpx.AsyncClient() as client:
            while queue and len(visited) < settings.max_pages_per_domain:
                url = queue.popleft()

                if url in visited:
                    continue
                if not same_registered_domain(url, seed_url):
                    continue
                if not self.robots.is_allowed(url):
                    logger.debug(f"Blocked by robots.txt: {url}")
                    continue

                visited.add(url)
                html = await self._fetch(client, url)

                if html is None:
                    continue

                results.append((url, html))
                logger.info(
                    f"Crawled [{len(visited)}/{settings.max_pages_per_domain}]: {url}"
                )

                # Enqueue discovered links
                for link in self._extract_links(html, url):
                    if link not in visited:
                        queue.append(link)

                # Politeness delay
                await asyncio.sleep(settings.crawl_delay_seconds)

        logger.info(f"Crawl complete. Pages fetched: {len(results)}")
        return results

    async def _try_sitemap(self, seed_url: str) -> list[str]:
        """
        Attempt to read /sitemap.xml and extract URLs from it.
        Returns a list of URLs found (may be empty).
        """
        sitemap_url = seed_url.rstrip("/") + "/sitemap.xml"
        urls = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    sitemap_url,
                    headers=self.headers,
                    timeout=settings.request_timeout_seconds,
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml-xml")
                    for loc in soup.find_all("loc"):
                        u = normalise_url(loc.get_text(strip=True))
                        if same_registered_domain(u, seed_url):
                            urls.append(u)
                    logger.info(f"Sitemap found: {len(urls)} URLs")
        except Exception as e:
            logger.debug(f"Sitemap not available at {sitemap_url}: {e}")
        return urls
