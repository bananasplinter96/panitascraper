import logging
from datetime import datetime, timezone
from typing import Generator

import scrapy
from scrapy.http import Response
from sqlalchemy.orm import Session

from models import ScrapeRun, get_engine
from panitascraper.items import ScrapedPageItem

logger = logging.getLogger(__name__)

_CONTENT_TYPE_TO_EXT = {
    "application/json": "json", "text/html": "html",
    "application/xml": "xml", "text/xml": "xml",
    "application/pdf": "pdf", "text/csv": "csv", "text/plain": "txt",
}


class BaseSpider(scrapy.Spider):
    name: str = "base"
    field_map: dict = {}
    status_map: dict = {}
    run_id: str | None = None

    def __init__(self, run_id: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_id = run_id
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = get_engine(self.settings.get("DATABASE_URL"))
        return self._engine

    def spider_closed(self, spider, reason):
        if not self.run_id:
            return
        status = "success" if reason == "finished" else "failed"
        errors = self.crawler.stats.get_value("spider_exceptions", 0) or 0
        items = self.crawler.stats.get_value("item_scraped_count", 0) or 0
        if errors > 0 and items > 0:
            status = "partial"
        elif errors > 0:
            status = "failed"
        with Session(self.engine) as session:
            run = session.get(ScrapeRun, self.run_id)
            if run:
                run.status = status
                run.finished_at = datetime.now(timezone.utc)
                session.commit()

    def _file_type_from_response(self, response: Response) -> str:
        ct = response.headers.get("Content-Type", b"").decode("utf-8", errors="ignore")
        for mime, ext in _CONTENT_TYPE_TO_EXT.items():
            if mime in ct:
                return ext
        return "bin"

    def make_item(self, response: Response, records: list[dict]) -> ScrapedPageItem:
        return ScrapedPageItem(
            url=response.url, body=response.body,
            file_type=self._file_type_from_response(response),
            spider_name=self.name, run_id=self.run_id, records=records,
        )

    def parse_records(self, response: Response) -> list[dict]:
        raise NotImplementedError

    def parse(self, response: Response, **kwargs) -> Generator:
        records = self.parse_records(response)
        self.crawler.stats.inc_value("records_extracted", len(records))
        yield self.make_item(response, records)
