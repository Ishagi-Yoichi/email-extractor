import logging

import tldextract
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.classifier.page_classifier import PageClassifier
from app.crawler.domain_crawler import DomainCrawler
from app.extractor.site_extractor import SiteExtractor
from app.harvester.email_harvester import EmailHarvester
from app.models import ArticlePage, CrawlRequest, CrawlResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Email Extractor",
    description="Crawl a domain → classify articles → extract external sites → harvest emails.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/crawl", response_model=CrawlResult)
async def crawl(request: CrawlRequest):
    """
    Full pipeline — Stages 1 through 4:
      1. Crawl all pages of the given domain
      2. Classify each page → article or not
      3. Extract external site references from article pages
      4. Harvest emails from those external sites → save to CSV
    """
    domain = request.domain.strip()
    if not domain:
        raise HTTPException(status_code=422, detail="domain must not be empty")

    if not domain.startswith(("http://", "https://")):
        domain = "https://" + domain

    seed_registered = tldextract.extract(domain).registered_domain
    if not seed_registered:
        raise HTTPException(status_code=422, detail=f"Could not parse domain: {domain}")

    logger.info(f"=== Pipeline start: {domain} ===")

    # ── Stage 1: crawl ────────────────────────────────────────────────────────
    crawler = DomainCrawler()
    pages: list[tuple[str, str]] = await crawler.crawl(domain)

    if not pages:
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch any pages from {domain}. "
            "Check the URL or robots.txt restrictions.",
        )

    # ── Stage 2: classify ─────────────────────────────────────────────────────
    classifier = PageClassifier()
    article_pages: list[tuple[str, str]] = []
    article_meta: list[ArticlePage] = []

    for url, html in pages:
        is_article, score = classifier.classify(url, html)
        if is_article:
            article_pages.append((url, html))
            article_meta.append(ArticlePage(url=url, score=score))

    logger.info(f"Article pages: {len(article_pages)}/{len(pages)}")

    # ── Stage 3: extract external sites ──────────────────────────────────────
    extractor = SiteExtractor()
    external_sites = extractor.extract(article_pages, domain)

    # ── Stage 4: harvest emails ───────────────────────────────────────────────
    csv_path: str | None = None
    emails_found = []

    if external_sites:
        harvester = EmailHarvester()
        emails_found, csv_path = await harvester.harvest(external_sites, domain)
        if not emails_found:
            logger.info("No emails found across all external sites.")
    else:
        logger.info("No external sites found — skipping harvest stage.")

    logger.info(f"=== Pipeline complete: {domain} ===")

    return CrawlResult(
        seed_domain=domain,
        pages_crawled=len(pages),
        article_pages=article_meta,
        external_sites=external_sites,
        emails_found=emails_found,
        csv_path=csv_path,
    )
