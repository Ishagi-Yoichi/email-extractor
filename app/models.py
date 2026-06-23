from typing import List

from pydantic import BaseModel, HttpUrl


class CrawlRequest(BaseModel):
    domain: str  # e.g. "https://example.com" or "example.com"


class ArticlePage(BaseModel):
    url: str
    score: int


class ExternalSite(BaseModel):
    domain: str  # registered domain, e.g. "acme.com"
    source_url: str  # article page where this domain was found
    raw_url: str  # the original href


class CrawlResult(BaseModel):
    seed_domain: str
    pages_crawled: int
    article_pages: List[ArticlePage]
    external_sites: List[ExternalSite]
