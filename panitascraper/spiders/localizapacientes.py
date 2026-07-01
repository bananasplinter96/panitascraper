"""
LocalizaPacientesSpider — spider for localizapacientes.com.
Optimizado para guardar resultados en tiempo real y evitar acumulación en memoria RAM.
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
    field_map = {
        "id":           "_id",
        "nombre":       "nombreCompleto",
        "edad":         "edad",
        "condicion":    "condicion",
        "hospital":     "hospital",
        "ciudad":       "ciudad",
        "estado":       "estado",
        "tipo_reporte": "condicion",
        "notas":        "direccion",
    }

    def transform_record(self, raw: dict) -> dict:
        raw["_id"] = f"localizapacientes:{raw.get('id', '')}"
        return raw

    allowed_domains = ["localizapacientes.com"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.3,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 8,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 8,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Registramos únicamente los IDs vistos para estadísticas
        self._seen: set[str] = set()

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self) -> AsyncIterator:
        # Guardamos la metadata de hospitales directamente
        yield scrapy.Request(
            f"{API_BASE}/hospitals",
            callback=self._parse_hospitals,
            errback=self.handle_error,
        )
        # Semilla inicial con prefijos de 2 letras: aa..zz (676 peticiones)
        for a in ALPHABET:
            for b in ALPHABET:
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

        # Emitimos el item de la página inmediatamente si contiene resultados
        if results:
            virtual_url = f"{API_BASE}/search?q={prefix}"
            yield ScrapedPageItem(
                url=virtual_url,
                body=response.body,
                file_type="json",
                spider_name=self.name,
                run_id=self.run_id,
                records=results,
            )

        # Control de estadísticas
        new_count = 0
        for rec in results:
            rid = rec.get("id")
            if rid and rid not in self._seen:
                self._seen.add(rid)
                new_count += 1

        logger.info("prefix=%r → %d results, %d new (total unique logged=%d)",
                    prefix, len(results), new_count, len(self._seen))

        # Si topamos el límite (50), expandimos recursivamente
        if len(results) >= RESULT_CAP and len(prefix) < MAX_DEPTH:
            for c in ALPHABET:
                yield self._search_request(prefix + c)

    def _search_error(self, failure) -> Generator:
        prefix = failure.request.meta.get("prefix", "?")
        logger.warning("Request failed for prefix=%r: %s", prefix, failure.value)

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