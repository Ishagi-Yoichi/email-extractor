import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)


class RobotsChecker:
    """
    Fetches and caches robots.txt for a domain.
    Falls back to allowing everything if robots.txt is unreachable.
    """

    def __init__(self, user_agent: str, timeout: int = 10):
        self.user_agent = user_agent
        self.timeout = timeout
        self._cache: dict[str, RobotFileParser] = {}

    def _base_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _fetch_parser(self, base_url: str) -> RobotFileParser:
        robots_url = f"{base_url}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(robots_url)
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                else:
                    # No robots.txt → allow all
                    parser.parse([])
        except Exception as e:
            logger.warning(f"Could not fetch robots.txt from {robots_url}: {e}")
            parser.parse([])
        return parser

    def is_allowed(self, url: str) -> bool:
        base = self._base_url(url)
        if base not in self._cache:
            self._cache[base] = self._fetch_parser(base)
        return self._cache[base].can_fetch(self.user_agent, url)
