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

    def open_spider(self, spider):
        self.engine = get_engine(self.database_url)

    def close_spider(self, spider):
        if self.engine:
            self.engine.dispose()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        body: bytes = adapter.get("body", b"")
        checksum = hashlib.sha256(body).hexdigest()
        adapter["checksum"] = checksum

        with Session(self.engine) as session:
            existing = session.get(ScrapedFile, checksum)

        adapter["is_new"] = existing is None
        if not adapter["is_new"]:
            logger.debug("Duplicate checksum %s for %s", checksum[:12], adapter.get("url"))
        return item
