import hashlib
import logging

from itemadapter import ItemAdapter
from sqlalchemy.orm import Session

from models import ScrapedFile, get_engine

logger = logging.getLogger(__name__)


class ChecksumPipeline:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(database_url=crawler.settings.get("DATABASE_URL"))

    def open_spider(self):
        self.engine = get_engine(self.database_url)

    def close_spider(self):
        if self.engine:
            self.engine.dispose()

    def process_item(self, item):
        adapter = ItemAdapter(item)
        body: bytes = adapter.get("body", b"")
        checksum = hashlib.sha256(body).hexdigest()
        adapter["checksum"] = checksum

        with Session(self.engine) as session:
            existing = session.get(ScrapedFile, checksum)

        adapter["is_new"] = existing is None
        if adapter["is_new"]:
            logger.info("New file %s checksum=%s type=%s",
                        adapter.get("url", ""), checksum[:12], adapter.get("file_type", "?"))
        else:
            logger.info("Duplicate %s checksum=%s",
                        adapter.get("url", ""), checksum[:12])
        return item
