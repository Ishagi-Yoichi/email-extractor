from typing import List, Optional

from pydantic import BaseModel


class CrawlRequest(BaseModel):
    domain: str  # e.g. "https://example.com" or "example.com"


class ArticlePage(BaseModel):
    url: str
    score: int


class ExternalSite(BaseModel):
    domain: str  # registered domain, e.g. "acme.com"
    source_url: str  # article page where this domain was found
    raw_url: str  # the original href


class EmailResult(BaseModel):
    email: str
    domain: str  # domain the email was found on
    found_on_page: str  # exact URL (e.g. acme.com/contact)
    source_article_urls: List[str]  # article pages that linked to this domain


class CrawlResult(BaseModel):
    seed_domain: str
    pages_crawled: int
    article_pages: List[ArticlePage]
    external_sites: List[ExternalSite]
    emails_found: List[EmailResult]
    csv_path: Optional[str] = None  # path to written CSV, if any results
