"""
LocalizadosVenezuelaSpider — spider for localizadosvenezuela.com.

Public REST API (no auth required, CORS open):
  GET /api/v1/localizados?page=<n>&limit=<n>
    → { data: [...], meta: { page, limit, total, totalPages } }
  GET /api/v1/localizados/{slug}
    → single record detail
  GET /api/v1/lugares
    → [{ slug, nombre, tipo, totalLocalizados }]  (64 locations)
  GET /api/v1/lugares/{slug}
    → location detail with its localizados

Strategy:
  1. Fetch /api/v1/lugares for location metadata (stored as its own item).
  2. Paginate /api/v1/localizados with limit=100 until all pages consumed.

Dataset: ~4,448 localizados across 64 lugares as of 2026-06-29.
Fields per record: slug, nombreCompleto, direccion, observaciones, condicion,
                   lugarSlug, lugarNombre, fuente, publicadoEn.
"""

import json
import logging
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

API_BASE = "https://localizadosvenezuela.com/api/v1"
PAGE_SIZE = 100


class LocalizadosVenezuelaSpider(BaseSpider):
    name = "localizadosvenezuela"
    allowed_domains = ["localizadosvenezuela.com"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.5,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 4,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
    }

    _headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    async def start(self) -> AsyncIterator:
        # Lugares metadata
        yield scrapy.Request(
            f"{API_BASE}/lugares",
            callback=self._parse_lugares,
            errback=self.handle_error,
            headers=self._headers,
        )
        # First page of localizados — subsequent pages yielded from parse()
        yield scrapy.Request(
            f"{API_BASE}/localizados?page=1&limit={PAGE_SIZE}",
            callback=self.parse,
            errback=self.handle_error,
            headers=self._headers,
            meta={"page": 1},
        )

    # ------------------------------------------------------------------
    # Lugares
    # ------------------------------------------------------------------

    def _parse_lugares(self, response: Response) -> Generator:
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error("Failed to parse lugares response")
            return
        lugares = data.get("data", data) if isinstance(data, dict) else data
        logger.info("%d lugares found", len(lugares))
        yield self.make_item(response, lugares)

    # ------------------------------------------------------------------
    # Localizados pagination
    # ------------------------------------------------------------------

    def parse(self, response: Response, **kwargs) -> Generator:
        page: int = response.meta.get("page", 1)

        if response.status != 200:
            logger.warning("HTTP %d on page %d", response.status, page)
            return

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error("JSON decode error on page %d", page)
            return

        records = data.get("data", [])
        meta = data.get("meta", {})
        total_pages = meta.get("totalPages", 1)
        total = meta.get("total", "?")

        if records:
            self.crawler.stats.inc_value("records_extracted", len(records))
            yield self.make_item(response, records)

        logger.info("Page %d/%d scraped (%d records, total=%s)", page, total_pages, len(records), total)

        if page < total_pages:
            next_page = page + 1
            yield scrapy.Request(
                f"{API_BASE}/localizados?page={next_page}&limit={PAGE_SIZE}",
                callback=self.parse,
                errback=self.handle_error,
                headers=self._headers,
                meta={"page": next_page},
            )

    def parse_records(self, response: Response) -> list[dict]:
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return []
        return data.get("data", [])

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
