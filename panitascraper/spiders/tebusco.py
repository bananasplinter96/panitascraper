"""
TeBuscoSpider — spider for tebusco.app.

PWA offline-first (Bootstrap + vanilla JS) respaldada por Supabase a través
de un gatekeeper PHP en /tebusco-portero.php.

Operaciones POST disponibles:
  { "op": "buscar", "q": "<texto>" }
    → array de hasta 80 registros (contiene búsqueda en nombre y cédula)
  { "op": "desaparecidos" }
    → array de hasta 100 registros con state="search" (offset ignorado)
  { "op": "reportar", "registro": {...} }  — escritura, no usada

No existe paginación real: el servidor ignora limit/offset.

Estrategia — exhaustión alfabética por CONTAINS:
  1. Iterar todos los bigrams aa..zz como query al portero.
  2. Si el resultado == 80 (cap), expandir a trigrams (prefijo + a..z).
  3. Continuar recursivamente hasta MAX_DEPTH.
  4. Deduplicar por uid antes de emitir el item final.

Dataset: ~7 281 registros totales (safe, hurt, search, reunited).
Campos: uid, name, cid, state, place, msg, by_who, phone,
        color_pulsera, codigo_pulsera, ts, updated_at.
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

PORTERO_URL = "https://www.tebusco.app/tebusco-portero.php"
RESULT_CAP = 80
ALPHABET = string.ascii_lowercase
MAX_DEPTH = 6

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


class TeBuscoSpider(BaseSpider):
    name = "tebusco"
    field_map = {
        "nombre":       "nombre",
        "cedula":       None,
        "edad":         "edad",
        "hospital":     "referencia",
        "ciudad":       None,
        "tipo_reporte": "estado",
        "condicion":    None,
        "estado":       "estadoUb",
        "notas":        "desc",
    }

    allowed_domains = ["www.tebusco.app"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.3,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 6,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 6,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._records: dict[str, dict] = {}  # dedup by uid
        self._pending: int = 0

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self) -> AsyncIterator:
        # Seed with all 2-char substring queries: aa..zz
        for a in ALPHABET:
            for b in ALPHABET:
                self._pending += 1
                yield self._buscar_request(a + b)

    # ------------------------------------------------------------------
    # Search requests (POST)
    # ------------------------------------------------------------------

    def _buscar_request(self, query: str) -> scrapy.Request:
        body = json.dumps({"op": "buscar", "q": query})
        return scrapy.Request(
            PORTERO_URL,
            method="POST",
            body=body,
            callback=self._parse_buscar,
            errback=self._buscar_error,
            headers=_HEADERS,
            meta={"query": query},
            dont_filter=True,  # same URL, different POST bodies
        )

    def _parse_buscar(self, response: Response) -> Generator:
        query: str = response.meta["query"]

        results: list[dict] = []
        if response.status == 200:
            try:
                results = json.loads(response.text)
                if not isinstance(results, list):
                    results = []
            except json.JSONDecodeError:
                logger.error("JSON decode error for query=%r", query)
        else:
            logger.warning("HTTP %d for query=%r", response.status, query)

        # Collect unique records
        before = len(self._records)
        for rec in results:
            uid = rec.get("uid")
            if uid:
                self._records[uid] = rec
        new_count = len(self._records) - before

        logger.debug(
            "query=%r → %d results, %d new (total unique=%d)",
            query, len(results), new_count, len(self._records),
        )

        # Expand sub-queries BEFORE decrementing to avoid false zero
        sub_requests: list[scrapy.Request] = []
        if len(results) >= RESULT_CAP and len(query) < MAX_DEPTH:
            for c in ALPHABET:
                sub_requests.append(self._buscar_request(query + c))
            self._pending += len(sub_requests)

        self._pending -= 1

        for req in sub_requests:
            yield req

        if self._pending == 0:
            yield from self._yield_aggregated()

    def _buscar_error(self, failure) -> Generator:
        query = failure.request.meta.get("query", "?")
        logger.warning("Request failed for query=%r: %s", query, failure.value)
        self._pending -= 1
        if self._pending == 0:
            yield from self._yield_aggregated()

    # ------------------------------------------------------------------
    # Final aggregated item
    # ------------------------------------------------------------------

    def _yield_aggregated(self) -> Generator:
        records = list(self._records.values())
        if not records:
            logger.warning("No records collected")
            return
        logger.info("Exhaustion complete — %d unique records", len(records))
        self.crawler.stats.set_value("records_unique", len(records))
        body = json.dumps(records).encode("utf-8")
        yield ScrapedPageItem(
            url=PORTERO_URL,
            body=body,
            file_type="json",
            spider_name=self.name,
            run_id=self.run_id,
            records=records,
        )

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def parse_records(self, response: Response) -> list[dict]:
        try:
            data = json.loads(response.text)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def parse(self, response: Response, **kwargs) -> Generator:
        yield from self._parse_buscar(response)

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
