"""
BusquedaVzlaSpider — single-endpoint JSON API spider for busquedavzla.netlify.app.

API endpoint: GET /api/reports
Response:     JSON array of missing-person reports (no pagination).

Each record contains: id, ts, nombre, apodo, edad, desc, estadoUb, referencia,
visto, estado, foto (base64 JPEG), notas, repEmail, repNombre, repRel, repTel.
"""

import json
import logging
from typing import AsyncIterator, Generator

from scrapy import Request
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

API_URL = "https://busquedavzla.netlify.app/api/reports"


class BusquedaVzlaSpider(BaseSpider):
    name = "busquedavzla"
    field_map = {
        "nombre":       "nombre",
        "cedula":       "cedula",
        "edad":         "edad",
        "hospital":     "hospital",
        "ciudad":       "ciudad",
        "tipo_reporte": "estado",
        "condicion":    "condicion",
        "estado":       "estado",
        "notas":        "notas",
    }

    allowed_domains = ["busquedavzla.netlify.app"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 1,
    }

    async def start(self) -> AsyncIterator:
        yield Request(
            API_URL,
            callback=self.parse,
            errback=self.handle_error,
            meta={"handle_httpstatus_list": [400, 403, 404, 429, 500]},
        )

    def parse(self, response: Response, **kwargs) -> Generator:
        if response.status != 200:
            logger.warning("Non-200 (%d) from %s", response.status, response.url)
            return

        records = self.parse_records(response)
        if records:
            self.crawler.stats.inc_value("records_extracted", len(records))
            yield self.make_item(response, records)

    def parse_records(self, response: Response) -> list[dict]:
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.error("JSON decode error for %s: %s", response.url, e)
            return []

        if not isinstance(data, list):
            logger.error("Unexpected response shape from %s", response.url)
            return []

        return data

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
