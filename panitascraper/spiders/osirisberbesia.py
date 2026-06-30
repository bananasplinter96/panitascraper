"""
OsirisBerbesiaSpider — spider for osirisberbesia.com/pacientesinfo/.

Sitio estático (sin API). Los 509 pacientes están todos embebidos en el
HTML de una sola página como elementos <details class="patient-card">.

Estructura de cada tarjeta:
  <details class="patient-card" data-search="<hospital> <nombre> <cedula> ...">
    <summary>
      <span class="patient-name">APELLIDO NOMBRE</span>
      <span class="patient-id">CEDULA</span>
    </summary>
    <div class="details-grid">
      <div><strong>Hospital</strong><span>...</span></div>
      <div><strong>Edad</strong><span>...</span></div>
      <div><strong>Teléfono</strong><span>...</span></div>
      <div><strong>Dirección</strong><span>...</span></div>
      <div class="detail-full"><strong>Observaciones</strong><span>...</span></div>
    </div>
  </details>

Dataset: 509 pacientes en una sola página.
Campos: nombre, cedula, hospital, edad, telefono, direccion, observaciones.
"""

import logging
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

URL = "https://osirisberbesia.com/pacientesinfo/"


class OsirisBerbesiaSpider(BaseSpider):
    name = "osirisberbesia"
    field_map = {
        "nombre":       "nombre",
        "cedula":       "cedula",
        "edad":         "edad",
        "hospital":     "hospital",
        "tipo_reporte": None,
        "ciudad":       None,
        "condicion":    None,
        "estado":       None,
        "notas":        "observaciones",
    }

    allowed_domains = ["osirisberbesia.com"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
    }

    async def start(self) -> AsyncIterator:
        yield scrapy.Request(
            URL,
            callback=self.parse,
            errback=self.handle_error,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )

    def parse(self, response: Response, **kwargs) -> Generator:
        records = self.parse_records(response)
        if not records:
            logger.warning("No patient records found — page structure may have changed")
            return
        self.crawler.stats.set_value("records_extracted", len(records))
        logger.info("%d patient records extracted", len(records))
        yield self.make_item(response, records)

    def parse_records(self, response: Response) -> list[dict]:
        records = []
        for card in response.css("details.patient-card"):
            nombre = card.css(".patient-name::text").get("").strip()
            cedula = card.css(".patient-id::text").get("").strip()

            # details-grid has <div><strong>Label</strong><span>Value</span></div>
            fields: dict[str, str] = {}
            for item in card.css(".details-grid div"):
                label = item.css("strong::text").get("").strip().lower()
                value = item.css("span::text").get("").strip()
                if label:
                    fields[label] = value

            records.append({
                "nombre": nombre,
                "cedula": cedula,
                "hospital": fields.get("hospital", ""),
                "edad": fields.get("edad", ""),
                "telefono": fields.get("teléfono", fields.get("telefono", "")),
                "direccion": fields.get("dirección", fields.get("direccion", "")),
                "observaciones": fields.get("observaciones", ""),
            })
        return records

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
