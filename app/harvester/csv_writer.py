import csv
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import TextIO

from app.models import EmailResult

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("output")

FIELDNAMES = ["email", "domain", "found_on_page", "source_article_urls"]


def _build_path(seed_domain: str) -> str:
    """Return a timestamped CSV filepath string (does not create the file)."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    safe_domain = (
        seed_domain.replace("https://", "")
        .replace("http://", "")
        .replace("/", "_")
        .strip("_")
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(OUTPUT_DIR / f"{safe_domain}_{timestamp}.csv")


class CsvWriter:
    """
    Progressive CSV writer — open once, append rows as emails arrive.
    Ensures results are persisted even if the pipeline is interrupted.
    """

    def __init__(self, seed_domain: str):
        self.path: str = _build_path(seed_domain)
        self._file: TextIO = io.open(self.path, "w", newline="", encoding="utf-8")
        self._writer: csv.DictWriter = csv.DictWriter(self._file, fieldnames=FIELDNAMES)
        self._writer.writeheader()
        self._file.flush()
        self._count: int = 0
        logger.info(f"CSV opened: {self.path}")

    def append(self, results: list[EmailResult]) -> None:
        """Write a batch of results immediately to disk."""
        for result in results:
            self._writer.writerow(
                {
                    "email": result.email,
                    "domain": result.domain,
                    "found_on_page": result.found_on_page,
                    "source_article_urls": " | ".join(result.source_article_urls),
                }
            )
        self._file.flush()
        self._count += len(results)
        if results:
            logger.info(f"  CSV: {self._count} emails saved so far → {self.path}")

    def close(self) -> None:
        self._file.close()
        logger.info(f"CSV closed: {self.path}  (total: {self._count} rows)")

    @property
    def count(self) -> int:
        return self._count
