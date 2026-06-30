"""
SismoEhrSpider — spider for sismo-ehr.chourio.dev.

Plataforma de contingencia multi-hospital (Next.js App Router + Netlify).
Expone una API pública sin autenticación:

  GET /api/publico?facility=<CODE>
    → { facility: { code, name }, rows: [...] }
    - 200 con rows vacío si el código existe pero no tiene datos
    - 429 si se excede el rate limit

El sistema soporta múltiples hospitales. La página pública de cada uno
es /publico/<CODE> y el QR de difusión es /publico/<CODE>/qr.

No existe un endpoint para listar todos los códigos activos. Los códigos
conocidos al momento de escribir este spider se enumeran en FACILITY_CODES.
Añadir nuevos códigos cuando se confirmen más hospitales en la plataforma.

Dataset conocido: 201 pacientes en DLU (Hospital General Dr. Domingo Luciani).
Campos: nombre, cedula, edad, sexo, servicio, estado, ingreso.

Estados posibles: "admitted" (Ingresado), "discharged" (Alta),
  "deceased" (Fallecido).
"""

import json
import logging
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

BASE_URL = "https://sismo-ehr.chourio.dev"
API_URL = f"{BASE_URL}/api/publico"

# Códigos de facilidad conocidos con datos públicos activos.
# Añadir nuevos códigos a medida que más hospitales se incorporen.
FACILITY_CODES: list[str] = [
    "DLU",  # Hospital General Dr. Domingo Luciani
]

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


class SismoEhrSpider(BaseSpider):
    name = "sismo_ehr"
    allowed_domains = ["sismo-ehr.chourio.dev"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS": 1,
    }

    async def start(self) -> AsyncIterator:
        for code in FACILITY_CODES:
            yield scrapy.Request(
                f"{API_URL}?facility={code}",
                callback=self.parse,
                errback=self.handle_error,
                headers=_HEADERS,
                meta={"facility_code": code},
            )

    def parse(self, response: Response, **kwargs) -> Generator:
        code: str = response.meta["facility_code"]

        if response.status == 429:
            logger.warning("Rate limited for facility=%s", code)
            return
        if response.status != 200:
            logger.warning("HTTP %d for facility=%s", response.status, code)
            return

        records = self.parse_records(response)
        if not records:
            logger.info("No records for facility=%s", code)
            return

        try:
            data = json.loads(response.text)
            facility = data.get("facility", {})
        except json.JSONDecodeError:
            facility = {}

        logger.info(
            "facility=%s (%s) → %d records",
            code, facility.get("name", "?"), len(records),
        )
        self.crawler.stats.inc_value("records_extracted", len(records))
        yield self.make_item(response, records)

    def parse_records(self, response: Response) -> list[dict]:
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return []
        rows = data.get("rows", [])
        if not isinstance(rows, list):
            return []
        # Enrich each row with facility metadata
        facility = data.get("facility", {})
        for row in rows:
            row.setdefault("facility_code", facility.get("code", ""))
            row.setdefault("facility_name", facility.get("name", ""))
        return rows

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
