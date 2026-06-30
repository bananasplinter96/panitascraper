"""
UbicameSpider — spider for 911.ubica.me (Úbícame).

Buscador unificado de víctimas del terremoto Venezuela 2026.
Los datos son archivos JSON estáticos (shards) servidos desde:

  GET /public/data/{LETRA}.json     → registros cuyo nombre empieza con esa letra
  GET /public/data/hospitales.json  → registros de origen HOSPITALES_VE

Shards: A-Z + hospitales.json = 27 archivos.
Totales aproximados (2026-06-29):
  - A-Z: ~43 301 registros
  - hospitales.json: ~1 057 registros
  Total: ~44 358 registros

Campos por registro:
  - person_record_id  : ID interno (e.g. "LP-1", "HOSP_982")
  - full_name         : nombre completo en mayúsculas
  - age               : edad como string
  - ext_venezuela_ci  : cédula venezolana (puede ser null)
  - phone             : teléfono (puede ser vacío)
  - last_known_location : último lugar conocido (hospital + piso/zona)
  - hospital          : nombre del hospital (no presente en hospitales.json)
  - notes             : observaciones
  - status            : "believed_alive" | "hospitalized" | otros
  - source            : "LISTADO_PERSONAS_VE_2026" | "HOSPITALES_VE"
  - source_date       : ISO 8601 timestamp

Codificación: los archivos JSON incluyen BOM UTF-8 (EF BB BF) —
Scrapy los lee como bytes y se decodifica manualmente antes de parsear.
"""

import json
import logging
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

BASE_URL = "https://911.ubica.me"
DATA_BASE = f"{BASE_URL}/public/data"

# 26 shards por letra + shard especial de hospitales
_SHARDS: list[tuple[str, str]] = (
    [(letter, f"{DATA_BASE}/{letter}.json") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    + [("hospitales", f"{DATA_BASE}/hospitales.json")]
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
}


class UbicameSpider(BaseSpider):
    name = "ubicame"
    field_map = {
        "nombre":       "full_name",
        "cedula":       "ext_venezuela_ci",
        "edad":         "age",
        "hospital":     "hospital",
        "ciudad":       None,
        "tipo_reporte": "status",
        "condicion":    None,
        "estado":       "status",
        "notas":        "notes",
    }

    allowed_domains = ["911.ubica.me"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.5,
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
    }

    async def start(self) -> AsyncIterator:
        for shard_key, url in _SHARDS:
            yield scrapy.Request(
                url,
                callback=self.parse,
                errback=self.handle_error,
                headers=_HEADERS,
                meta={"shard": shard_key},
            )

    def parse(self, response: Response, **kwargs) -> Generator:
        shard: str = response.meta["shard"]

        if response.status != 200:
            logger.warning("HTTP %d for shard=%s", response.status, shard)
            return

        records = self.parse_records(response)
        if not records:
            logger.warning("No records in shard=%s", shard)
            return

        self.crawler.stats.inc_value("records_extracted", len(records))
        logger.info("shard=%s → %d records", shard, len(records))
        yield self.make_item(response, records)

    def parse_records(self, response: Response) -> list[dict]:
        # Strip UTF-8 BOM if present (EF BB BF) before JSON parsing
        raw: bytes = response.body
        if raw[:3] == b"\xef\xbb\xbf":
            raw = raw[3:]
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("JSON decode error in shard=%s: %s", response.meta.get("shard"), e)
            return []

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
