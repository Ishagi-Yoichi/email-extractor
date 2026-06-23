from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    max_pages_per_domain: int = 100
    crawl_delay_seconds: float = 1.0
    request_timeout_seconds: int = 15
    max_concurrent_requests: int = 5

    classifier_pass_threshold: int = 60
    classifier_drop_threshold: int = 30

    user_agent: str = "Mozilla/5.0 (compatible; EmailExtractorBot/1.0)"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
