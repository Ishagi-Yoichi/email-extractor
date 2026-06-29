import asyncio
import logging
import re
from urllib.parse import urljoin

import httpx

from app.config import settings
from app.harvester.csv_writer import CsvWriter
from app.models import EmailResult, ExternalSite

logger = logging.getLogger(__name__)

# Pages to probe on each external domain, in priority order
PRIORITY_PATHS = [
    "/contact",
    "/contact-us",
    "/contact_us",
    "/about",
    "/about-us",
    "/about_us",
    "/team",
    "/people",
    "/imprint",  # common in EU sites
    "/impressum",  # German sites
    "",  # homepage (footer)
]

# Regex: matches standard emails
EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# Patterns that indicate a placeholder, not a real email
PLACEHOLDER_PATTERNS = re.compile(
    r"(example\.|@example|sentry\.|@sentry|yourdomain|placeholder|noreply@nore|"
    r"test@test|foo@bar|user@user|email@email|name@name)",
    re.IGNORECASE,
)

# Split timeout: connect fast, allow more time to read
HARVEST_TIMEOUT = httpx.Timeout(
    connect=settings.harvest_connect_timeout_seconds,
    read=settings.harvest_read_timeout_seconds,
    write=5,
    pool=5,
)


def _is_valid_email(email: str) -> bool:
    """Basic format validation — no MX lookup."""
    if len(email) > 254:
        return False
    if PLACEHOLDER_PATTERNS.search(email):
        return False
    _, _, domain = email.partition("@")
    if "." not in domain:
        return False
    tld = domain.rsplit(".", 1)[-1]
    if not (2 <= len(tld) <= 12):
        return False
    return True


def _extract_emails_from_html(html: str) -> set[str]:
    """Pull all valid emails from raw HTML, decoding common obfuscations."""
    decoded = html.replace("[at]", "@").replace(" at ", "@").replace("(at)", "@")
    decoded = decoded.replace("[dot]", ".").replace("(dot)", ".")
    found = EMAIL_REGEX.findall(decoded)
    return {e.lower() for e in found if _is_valid_email(e)}


class EmailHarvester:
    """
    For each unique external domain, fetches priority pages and extracts emails.
    Writes results progressively to CSV so partial results are never lost.
    """

    def __init__(self):
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_requests)
        self.headers = {"User-Agent": settings.user_agent}

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> str | None:
        """Fetch a single URL with split timeouts."""
        async with self.semaphore:
            try:
                resp = await client.get(
                    url,
                    headers=self.headers,
                    timeout=HARVEST_TIMEOUT,
                    follow_redirects=True,
                )
                if resp.status_code == 200 and "text/html" in resp.headers.get(
                    "content-type", ""
                ):
                    return resp.text
            except httpx.TimeoutException:
                logger.debug(f"Timeout: {url}")
            except Exception as e:
                logger.debug(f"Failed: {url} — {e}")
            return None

    async def _harvest_domain(
        self,
        client: httpx.AsyncClient,
        domain: str,
        source_urls: list[str],
        csv_writer: CsvWriter,
    ) -> list[EmailResult]:
        """
        Probe all priority paths for one domain.
        Each batch of emails is written to CSV immediately as found.
        The entire domain is wrapped in a hard timeout.
        """
        base = f"https://{domain}"
        results: list[EmailResult] = []
        seen_emails: set[str] = set()

        async def _probe() -> None:
            for path in PRIORITY_PATHS:
                url = urljoin(base, path) if path else base
                html = await self._fetch(client, url)
                if not html:
                    continue

                emails = _extract_emails_from_html(html)
                new_emails = emails - seen_emails
                seen_emails.update(new_emails)

                if new_emails:
                    batch = [
                        EmailResult(
                            email=email,
                            domain=domain,
                            found_on_page=url,
                            source_article_urls=source_urls,
                        )
                        for email in new_emails
                    ]
                    results.extend(batch)
                    #  Write to CSV immediately
                    csv_writer.append(batch)
                    for r in batch:
                        logger.info(f"  Found: {r.email}  on {url}")

                await asyncio.sleep(settings.crawl_delay_seconds * 0.5)

        try:
            await asyncio.wait_for(
                _probe(),
                timeout=settings.harvest_domain_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"Domain timed out after {settings.harvest_domain_timeout_seconds}s: {domain}"
                f" — kept {len(results)} email(s) found before timeout"
            )

        if not results:
            logger.debug(f"No emails found: {domain}")

        return results

    async def harvest(
        self,
        external_sites: list[ExternalSite],
        seed_domain: str,
    ) -> tuple[list[EmailResult], str | None]:
        """
        Harvest emails from all unique external domains.
        Opens the CSV upfront — results are flushed to disk as each domain finishes.

        Returns (all_results, csv_path). csv_path is None if no emails were found.
        """
        # Group source article URLs by domain
        domain_sources: dict[str, list[str]] = {}
        for site in external_sites:
            domain_sources.setdefault(site.domain, [])
            if site.source_url not in domain_sources[site.domain]:
                domain_sources[site.domain].append(site.source_url)

        logger.info(f"Harvesting from {len(domain_sources)} unique external domains...")

        csv_writer = CsvWriter(seed_domain)
        all_results: list[EmailResult] = []

        try:
            async with httpx.AsyncClient() as client:
                tasks = [
                    self._harvest_domain(client, domain, sources, csv_writer)
                    for domain, sources in domain_sources.items()
                ]
                domain_results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in domain_results:
                if isinstance(res, BaseException):
                    logger.warning(f"Harvest task failed: {res}")
                elif isinstance(res, list):
                    all_results.extend(res)

        finally:
            # Always close the CSV — even if gather raises or is cancelled
            csv_writer.close()

        logger.info(f"Total emails harvested: {len(all_results)}")
        csv_path = csv_writer.path if csv_writer.count > 0 else None
        return all_results, csv_path
