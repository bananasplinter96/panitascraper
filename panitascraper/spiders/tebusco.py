"""
TeBuscoSpider — spider for tebusco.app.
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
        "id":                "_id",
        "nombre":            "name",
        "cedula":            "cid",
        "tipo_reporte":      "state",
        "estado":            "state",
        "ultimo_lugar":      "place",
        "reportero_nombre":  "by_who",
        "telefono_familiar": "phone",
        "notas":             "_notas",
    }

    def transform_record(self, raw: dict) -> dict:
        raw["_id"] = f"tebusco:{raw.get('uid', '')}"
        parts = [p for p in (
            raw.get("msg"),
            f"Pulsera: {raw['color_pulsera']}" if raw.get("color_pulsera") else None,
            f"Código pulsera: {raw['codigo_pulsera']}" if raw.get("codigo_pulsera") else None,
        ) if p]
        raw["_notas"] = " | ".join(parts)
        return raw

    allowed_domains = ["www.tebusco.app"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.3,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 6,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 6,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo guardamos los UIDs vistos para control de estadísticas en consola
        self._seen: set[str] = set()

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self) -> AsyncIterator:
        # Semilla con todas las combinaciones de 2 caracteres: aa..zz
        for a in ALPHABET:
            for b in ALPHABET:
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
            dont_filter=True,  # Mismo URL, diferentes cuerpos POST
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

        # Si obtuvimos resultados, los enviamos a almacenar inmediatamente
        if results:
            # Generamos una URL virtual única para que se cree un archivo diferente por búsqueda
            virtual_url = f"{PORTERO_URL}?q={query}"
            yield ScrapedPageItem(
                url=virtual_url,
                body=response.body,
                file_type="json",
                spider_name=self.name,
                run_id=self.run_id,
                records=results,
            )

        # Calculamos estadísticas de duplicados para mantenerte informado en consola
        new_count = 0
        for rec in results:
            uid = rec.get("uid")
            if uid and uid not in self._seen:
                self._seen.add(uid)
                new_count += 1

        logger.info(
            "query=%r → %d results, %d new (total unique logged=%d)",
            query, len(results), new_count, len(self._seen),
        )

        # Si alcanzamos el límite del API (80) y no hemos llegado a la profundidad máxima,
        # expandimos la búsqueda agregando un tercer carácter (ej. "jua", "jub"...)
        if len(results) >= RESULT_CAP and len(query) < MAX_DEPTH:
            for c in ALPHABET:
                yield self._buscar_request(query + c)

    def _buscar_error(self, failure) -> Generator:
        query = failure.request.meta.get("query", "?")
        logger.warning("Request failed for query=%r: %s", query, failure.value)

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