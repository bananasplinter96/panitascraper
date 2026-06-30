"""
LocalizaPacientesSpider — spider for localizapacientes.com.

Next.js app backed by a simple search API:
  GET /api/search?q=<term>  →  { resultados: [...], total: N }  (cap: 50 per query)
  GET /api/hospitals         →  list of 19 hospitals with patient counts
  GET /api/stats             →  aggregate counts

No paginated bulk endpoint exists. Strategy: alphabetic prefix exhaustion.
  1. Seed with all 2-letter prefixes (aa … zz).
  2. Any prefix returning exactly 50 results (the API cap) expands into
     26 3-letter sub-prefixes.
  3. Recurse up to MAX_DEPTH letters deep.
  4. All unique records are collected in memory (keyed by ID).
  5. The last callback to complete detects pending==0 and yields the
     aggregated item through the pipeline.

Current dataset: ~3,656 patients across 19 Caracas hospitals.
Fields per record: id, nombreCompleto, edad, condicion, hospital, ciudad,
                   estado, fechaIngreso, lat, lng, direccion.
"""

import json
import logging
import string
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.items import ScrapedPageItem
from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

API_BASE = "https://localizapacientes.com/api"
RESULT_CAP = 50          # API hard cap per query
ALPHABET = string.ascii_lowercase
MAX_DEPTH = 6            # safety ceiling


class LocalizaPacientesSpider(BaseSpider):
    name = "localizapacientes"
    allowed_domains = ["localizapacientes.com"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.3,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 8,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 8,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._records: dict[str, dict] = {}   # dedup by patient ID
        self._pending: int = 0                 # in-flight search requests

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self) -> AsyncIterator:
        # Store hospital metadata as its own item
        yield scrapy.Request(
            f"{API_BASE}/hospitals",
            callback=self._parse_hospitals,
            errback=self.handle_error,
        )
        # Seed 2-letter prefixes: aa, ab, … zz  (676 requests)
        for a in ALPHABET:
            for b in ALPHABET:
                self._pending += 1
                yield self._search_request(a + b)

    # ------------------------------------------------------------------
    # Hospitals
    # ------------------------------------------------------------------

    def _parse_hospitals(self, response: Response) -> Generator:
        try:
            hospitals = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error("Failed to parse hospitals response")
            return
        logger.info("%d hospitals found", len(hospitals))
        yield self.make_item(response, hospitals)

    # ------------------------------------------------------------------
    # Search prefix exhaustion
    # ------------------------------------------------------------------

    def _search_request(self, prefix: str) -> scrapy.Request:
        return scrapy.Request(
            f"{API_BASE}/search?q={prefix}",
            callback=self._parse_search,
            errback=self._search_error,
            meta={"prefix": prefix},
            headers={"Accept": "application/json"},
        )

    def _parse_search(self, response: Response) -> Generator:
        prefix: str = response.meta["prefix"]

        results: list[dict] = []
        if response.status == 200:
            try:
                data = json.loads(response.text)
                results = data.get("resultados", [])
            except json.JSONDecodeError:
                logger.error("JSON decode error for prefix=%r", prefix)
        else:
            logger.warning("HTTP %d for prefix=%r", response.status, prefix)

        # Collect unique records
        before = len(self._records)
        for rec in results:
            rid = rec.get("id")
            if rid:
                self._records[rid] = rec
        new_count = len(self._records) - before

        logger.debug("prefix=%r → %d results, %d new (total=%d)",
                     prefix, len(results), new_count, len(self._records))

        # Expand sub-prefixes BEFORE decrementing, to avoid false zero
        sub_requests: list[scrapy.Request] = []
        if len(results) >= RESULT_CAP and len(prefix) < MAX_DEPTH:
            for c in ALPHABET:
                sub_requests.append(self._search_request(prefix + c))
            self._pending += len(sub_requests)

        # Now decrement for the completed request
        self._pending -= 1

        for req in sub_requests:
            yield req

        # If this was the last in-flight request, emit the aggregated item
        if self._pending == 0:
            yield from self._yield_aggregated()

    def _search_error(self, failure) -> Generator:
        prefix = failure.request.meta.get("prefix", "?")
        logger.warning("Request failed for prefix=%r: %s", prefix, failure.value)
        self._pending -= 1
        if self._pending == 0:
            yield from self._yield_aggregated()

    # ------------------------------------------------------------------
    # Final aggregated item
    # ------------------------------------------------------------------

    def _yield_aggregated(self) -> Generator:
        records = list(self._records.values())
        if not records:
            logger.warning("No patient records collected")
            return
        logger.info("Prefix exhaustion complete — %d unique patients", len(records))
        self.crawler.stats.set_value("patients_unique", len(records))
        body = json.dumps(records).encode("utf-8")
        yield ScrapedPageItem(
            url=f"{API_BASE}/search",
            body=body,
            file_type="json",
            spider_name=self.name,
            run_id=self.run_id,
            records=records,
        )

    # ------------------------------------------------------------------
    # Required BaseSpider overrides
    # ------------------------------------------------------------------

    def parse_records(self, response: Response) -> list[dict]:
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return []
        return data.get("resultados", [])

    def parse(self, response: Response, **kwargs) -> Generator:
        yield from self._parse_search(response)

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
