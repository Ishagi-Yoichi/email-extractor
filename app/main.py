import logging

import tldextract
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.classifier.page_classifier import PageClassifier
from app.crawler.domain_crawler import DomainCrawler
from app.extractor.site_extractor import SiteExtractor
from app.models import ArticlePage, CrawlRequest, CrawlResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Email Extractor — Phase 1",
    description="Crawl a domain, classify article pages, extract external sites.",
    version="0.1.0",
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
    Stage 1–3 pipeline:
      1. Crawl all pages of the given domain
      2. Classify each page → article or not
      3. Extract external site references from article pages
    """
    domain = request.domain.strip()
    if not domain:
        raise HTTPException(status_code=422, detail="domain must not be empty")

    # Ensure we have a scheme
    if not domain.startswith(("http://", "https://")):
        domain = "https://" + domain

    seed_registered = tldextract.extract(domain).registered_domain
    if not seed_registered:
        raise HTTPException(status_code=422, detail=f"Could not parse domain: {domain}")

    logger.info(f"=== Starting pipeline for: {domain} ===")

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

    logger.info(f"Article pages identified: {len(article_pages)}/{len(pages)}")

    # ── Stage 3: extract external sites ──────────────────────────────────────
    extractor = SiteExtractor()
    external_sites = extractor.extract(article_pages, domain)

    return CrawlResult(
        seed_domain=domain,
        pages_crawled=len(pages),
        article_pages=article_meta,
        external_sites=external_sites,
    )
