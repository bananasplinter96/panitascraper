"""
ReencuentroHelpSpider — spider for reencuentro.help.
Optimizado para guardar los registros de forma progresiva (página por página).
"""

import json
import logging
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.items import ScrapedPageItem
from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

SUPA_URL = "https://rwqhswywmdjqyqnpsxqw.supabase.co"
LIST_URL = f"{SUPA_URL}/functions/v1/list-records"

KINDS = ("missing", "found")
PAGE_SIZE = 24          # fixed by server
TOTAL_CAP = 5_000       # API hard cap per kind
MAX_PAGES = (TOTAL_CAP + PAGE_SIZE - 1) // PAGE_SIZE  # 209
NO_NEW_WINDOW = 20

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


class ReencuentroHelpSpider(BaseSpider):
    name = "reencuentrohelp"
    allowed_domains = ["reencuentro.help", "rwqhswywmdjqyqnpsxqw.supabase.co"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.3,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 4,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Estado de deduplicación por tipo
        self._seen: dict[str, set[str]] = {k: set() for k in KINDS}
        self._no_new: dict[str, int] = {k: 0 for k in KINDS}

    # ------------------------------------------------------------------

    async def start(self) -> AsyncIterator:
        for kind in KINDS:
            yield self._list_request(kind, page=1)

    def _list_request(self, kind: str, page: int) -> scrapy.Request:
        return scrapy.Request(
            LIST_URL,
            method="POST",
            body=json.dumps({"kind": kind, "page": page}),
            callback=self._parse_list,
            errback=self._list_error,
            headers=_HEADERS,
            meta={"kind": kind, "page": page},
            dont_filter=True,
        )

    def _parse_list(self, response: Response) -> Generator:
        kind: str = response.meta["kind"]
        page: int = response.meta["page"]

        if response.status != 200:
            logger.warning("HTTP %d kind=%s page=%d", response.status, kind, page)
            return

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error("JSON error kind=%s page=%d", kind, page)
            return

        records: list[dict] = data.get("records", [])
        
        # Guardamos la página actual de manera progresiva
        if records:
            # Creamos una URL virtual única para que la pipeline lo diferencie y guarde por separado
            virtual_url = f"{LIST_URL}?kind={kind}&page={page}"
            yield ScrapedPageItem(
                url=virtual_url,
                body=response.body,
                file_type="json",
                spider_name=self.name,
                run_id=self.run_id,
                records=records,
            )

        # Calculamos cuántos registros nuevos hay en esta página para el control de parada
        new_count = 0
        for rec in records:
            rid = rec.get("id")
            if rid and rid not in self._seen[kind]:
                self._seen[kind].add(rid)
                new_count += 1

        logger.info("kind=%s page=%d → %d records, %d new (total unique=%d)",
                    kind, page, len(records), new_count, len(self._seen[kind]))

        if new_count == 0:
            self._no_new[kind] += 1
        else:
            self._no_new[kind] = 0

        # Continuar si: estamos dentro del límite AND no nos hemos estancado AND no completamos el total
        should_continue = (
            page < MAX_PAGES
            and self._no_new[kind] < NO_NEW_WINDOW
            and len(self._seen[kind]) < TOTAL_CAP
        )

        if should_continue:
            yield self._list_request(kind, page + 1)
        else:
            reason = (
                "page cap" if page >= MAX_PAGES
                else f"no new in {NO_NEW_WINDOW} pages" if self._no_new[kind] >= NO_NEW_WINDOW
                else "total cap reached"
            )
            logger.info("kind=%s done (%s) — %d unique records", kind, reason, len(self._seen[kind]))

    def _list_error(self, failure) -> Generator:
        kind = failure.request.meta.get("kind", "?")
        page = failure.request.meta.get("page", "?")
        logger.warning("Request failed kind=%s page=%s: %s", kind, page, failure.value)

    # ------------------------------------------------------------------

    def parse_records(self, response: Response) -> list[dict]:
        try:
            data = json.loads(response.text)
            return data.get("records", [])
        except json.JSONDecodeError:
            return []

    def parse(self, response: Response, **kwargs) -> Generator:
        yield from self._parse_list(response)

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")