from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    max_pages_per_domain: int = 1000
    crawl_delay_seconds: float = 1.0
    request_timeout_seconds: int = 15
    max_concurrent_requests: int = 5

    # Harvester-specific timeouts (split for finer control)
    harvest_connect_timeout_seconds: int = 5  # fail fast if host doesn't respond
    harvest_read_timeout_seconds: int = 10  # max time to read the response body
    harvest_domain_timeout_seconds: int = 30  # hard cap per entire domain (all paths)

    classifier_pass_threshold: int = 60
    classifier_drop_threshold: int = 30

    user_agent: str = "Mozilla/5.0 (compatible; EmailExtractorBot/1.0)"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
