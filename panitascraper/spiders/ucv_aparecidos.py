"""
UcvAparecidosSpider — single-endpoint JSON API spider for ucv-aparecidos.vercel.app.

API endpoints:
  GET /api/estudiantes  → JSON array of 540 student records (main data)
  GET /api/facultades   → dict mapping faculty → list of careers (reference data)
  GET /api/stats        → aggregate counts by status and faculty

Each estudiante record contains: id, nombre, cedula, semestre, ultima_ubicacion,
descripcion, fecha_registro, registrado_por, fecha_aparecio, tipo_confirmacion,
detalles_confirmacion, reportado_aparicion_por, contacto_reportador, tipo,
latitud, longitud, estado, carrera, facultad, nombre_contacto, relacion_contacto,
telefono_contacto, foto_signed_url.

Estados: desaparecido, aparecido, fallecido.
"""

import json
import logging
from typing import AsyncIterator, Generator

from scrapy import Request
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

BASE_URL = "https://ucv-aparecidos.vercel.app/api"


class UcvAparecidosSpider(BaseSpider):
    name = "ucv_aparecidos"
    field_map = {
        "id":                    "_id",
        "nombre":                "nombre",
        "cedula":                "cedula",
        "foto_url":              "foto_signed_url",
        "tipo_reporte":          "estado",
        "estado":                "estado",
        "ultimo_lugar":          "ultima_ubicacion",
        "confirmacion_tipo":     "tipo_confirmacion",
        "confirmacion_detalle":  "detalles_confirmacion",
        "contacto_familiar":     "nombre_contacto",
        "telefono_familiar":     "telefono_contacto",
        "reportero_nombre":      "_reportero_nombre",
        "reportero_telefono":    "contacto_reportador",
        "notas":                 "_notas",
    }

    def transform_record(self, raw: dict) -> dict:
        raw["_id"] = f"ucv:{raw.get('id', '')}"
        raw["_reportero_nombre"] = (
            raw.get("reportado_aparicion_por") or raw.get("registrado_por") or ""
        )
        parts = [p for p in (
            raw.get("descripcion"),
            f"Carrera: {raw['carrera']}" if raw.get("carrera") else None,
            f"Facultad: {raw['facultad']}" if raw.get("facultad") else None,
        ) if p]
        raw["_notas"] = " | ".join(parts)
        return raw

    allowed_domains = ["ucv-aparecidos.vercel.app"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 1,
    }

    async def start(self) -> AsyncIterator:
        yield Request(
            f"{BASE_URL}/estudiantes",
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
