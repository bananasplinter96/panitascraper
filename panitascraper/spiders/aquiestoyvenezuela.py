"""
AquiEstoyVenezuelaSpider — spider for aquiestoyvenezuela.com.

Stack: Vanilla JS + Supabase JS SDK. En producción usa un lector PHP propio
(/db-reader/) para mantener credenciales fuera del navegador.

Endpoints relevantes:
  GET /db-reader/stats.php
    → { success, total, desaparecidos, encontrados }

  GET /db-reader/personas.php?offset=<n>&limit=<n>[&q=<text>&status=<s>...]
    → { success, records: [...], hasMore: bool, limit: int, offset: int }
    Parámetros opcionales: q, category, status, edad, orden,
                           tipoUbicacion, ubicacion.
    Limit máximo: 100.

Dataset: ~66 834 registros (63 760 desaparecidos + 3 074 encontrados).

Campos por registro: id, nombre, cedula, edad, ciudad, ultima_ubicacion,
  telefono_contacto, nombre_de_quien_lo_busca, observaciones, estado,
  ubicacion_encontrado, encontrado_por, encontrado_por_cedula,
  telefono_quien_encuentra, foto_url, fecha_registro,
  fecha_actualizacion, es_menor.
"""

import json
import logging
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

BASE_URL = "https://aquiestoyvenezuela.com/db-reader"
PAGE_SIZE = 100

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


class AquiEstoyVenezuelaSpider(BaseSpider):
    name = "aquiestoyvenezuela"
    allowed_domains = ["aquiestoyvenezuela.com"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.5,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 4,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
    }

    async def start(self) -> AsyncIterator:
        # Stats metadata
        yield scrapy.Request(
            f"{BASE_URL}/stats.php",
            callback=self._parse_stats,
            errback=self.handle_error,
            headers=_HEADERS,
        )
        # First page — subsequent pages yielded from parse()
        yield self._page_request(offset=0)

    def _page_request(self, offset: int) -> scrapy.Request:
        return scrapy.Request(
            f"{BASE_URL}/personas.php?offset={offset}&limit={PAGE_SIZE}",
            callback=self.parse,
            errback=self.handle_error,
            headers=_HEADERS,
            meta={"offset": offset},
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def _parse_stats(self, response: Response) -> Generator:
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error("Failed to parse stats.php")
            return
        logger.info(
            "Stats — total=%s desaparecidos=%s encontrados=%s",
            data.get("total"), data.get("desaparecidos"), data.get("encontrados"),
        )
        yield self.make_item(response, [data])

    # ------------------------------------------------------------------
    # Personas pagination
    # ------------------------------------------------------------------

    def parse(self, response: Response, **kwargs) -> Generator:
        offset: int = response.meta.get("offset", 0)

        if response.status != 200:
            logger.warning("HTTP %d at offset=%d", response.status, offset)
            return

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error("JSON decode error at offset=%d", offset)
            return

        records = data.get("records", [])
        has_more = data.get("hasMore", False)

        if records:
            self.crawler.stats.inc_value("records_extracted", len(records))
            yield self.make_item(response, records)

        logger.info(
            "offset=%d → %d records | hasMore=%s",
            offset, len(records), has_more,
        )

        if has_more:
            yield self._page_request(offset=offset + PAGE_SIZE)

    def parse_records(self, response: Response) -> list[dict]:
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return []
        return data.get("records", [])

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
