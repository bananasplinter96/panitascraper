"""
EncuentralosSpider — paginated JSON API spider for encuentralos.tecnosoft.dev.

API endpoint: GET /api/personas?limit=100&offset=0
Response:     {"items": [...], "total": 97713}

Each record contains: id, nombre, edad, sexo, descripcion, foto,
ultima_ubicacion, ultima_lat, ultima_lng, ultima_vez, reporta_contacto,
estado, creado, cedula, pv_por, pv_contacto, pv_lugar, pv_salud, pv_relacion.
"""

import json
import logging
from typing import AsyncIterator, Generator

from scrapy import Request
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

PAGE_SIZE = 100


class EncuentralosSpider(BaseSpider):
    name = "encuentralos"
    allowed_domains = ["encuentralos.tecnosoft.dev"]

    field_map = {
        "id":                 "_id",
        "nombre":             "nombre",
        "edad":               "edad",
        "cedula":             "cedula",
        "sexo":               "sexo",
        "foto_url":           "foto",
        "tipo_reporte":       "estado",
        "estado":             "estado",
        "ultimo_lugar":       "ultima_ubicacion",
        "telefono_familiar":  "reporta_contacto",
        "descripcion_fisica": "descripcion",
        "reportero_nombre":   "pv_por",
        "reportero_telefono": "pv_contacto",
        "hospital":           "pv_lugar",
        "condicion":          "pv_salud",
    }

    def transform_record(self, raw: dict) -> dict:
        raw["_id"] = f"encuentralos:{raw.get('id', '')}"
        return raw

    custom_settings = {
        "DOWNLOAD_DELAY": 0.5,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 4,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
    }

    async def start(self) -> AsyncIterator:
        url = f"https://encuentralos.tecnosoft.dev/api/personas?limit={PAGE_SIZE}&offset=0"
        yield Request(url, callback=self.parse, errback=self.handle_error,
                      meta={"handle_httpstatus_list": [400, 403, 404, 429, 500]})

    def parse(self, response: Response, **kwargs) -> Generator:
        if response.status != 200:
            logger.warning("Non-200 (%d) from %s", response.status, response.url)
            return

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.error("JSON decode error for %s: %s", response.url, e)
            return

        records = data.get("items", [])
        total = data.get("total", 0)

        if records:
            yield self.make_item(response, records)
            self.crawler.stats.inc_value("records_extracted", len(records))

        offset = self._extract_offset(response.url)
        next_offset = offset + PAGE_SIZE
        if next_offset < total:
            next_url = f"https://encuentralos.tecnosoft.dev/api/personas?limit={PAGE_SIZE}&offset={next_offset}"
            yield Request(next_url, callback=self.parse, errback=self.handle_error,
                          meta={"handle_httpstatus_list": [400, 403, 404, 429, 500]})

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")

    def parse_records(self, response: Response) -> list[dict]:
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return []
        return data.get("items", [])

    @staticmethod
    def _extract_offset(url: str) -> int:
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(url).query)
        try:
            return int(qs.get("offset", [0])[0])
        except (ValueError, IndexError):
            return 0
