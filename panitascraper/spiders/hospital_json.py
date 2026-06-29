"""
HospitalJsonSpider — example spider for a JSON API returning patient lists.

Configure via spider_config row:
    name: "hospital_json"
    urls: ["https://example-hospital.gov.ve/api/pacientes"]
    args: {"auth_token": "Bearer abc123"}
    schedule: "0 */12 * * *"

Expected response shape:
    {"pacientes": [{"nombre_completo": "...", "cedula": "...", ...}]}
"""

import json
import logging

from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)


class HospitalJsonSpider(BaseSpider):
    name = "hospital_json"

    field_map = {
        "nombre":       "nombre_completo",
        "cedula":       "cedula",
        "edad":         "edad",
        "tipo_reporte": "condicion",
        "hospital":     "hospital",
        "ciudad":       "ciudad",
        "condicion":    "estado_paciente",
        "estado":       None,
        "notas":        "observaciones",
    }

    status_map = {
        "ingresado": "ingresado", "fallecido": "fallecido",
        "alta médica": "ingresado", "transferido": "ingresado",
        "desaparecido": "desaparecido",
    }

    custom_settings = {"DOWNLOAD_DELAY": 2.0, "RANDOMIZE_DOWNLOAD_DELAY": True}

    def start_requests(self):
        urls = getattr(self, "urls", None) or []
        auth_token = getattr(self, "auth_token", None)
        headers = {"Authorization": auth_token} if auth_token else {}
        for url in urls:
            yield self.make_request(url, headers)

    def make_request(self, url, headers=None):
        from scrapy import Request
        return Request(url, headers=headers or {}, callback=self.parse,
                       errback=self.handle_error,
                       meta={"handle_httpstatus_list": [400, 403, 404, 429, 500]})

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")

    def parse_records(self, response: Response) -> list[dict]:
        if response.status != 200:
            logger.warning("Non-200 (%d) from %s", response.status, response.url)
            return []
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.error("JSON decode error for %s: %s", response.url, e)
            return []

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("pacientes", "patients", "data", "results", "items"):
                if key in data:
                    return data[key]
            return list(data.values())[0] if data else []
        return []

    def transform_record(self, raw: dict) -> dict:
        if "nombre_completo" in raw:
            raw["nombre_completo"] = " ".join(raw["nombre_completo"].split())
        if raw.get("cedula") is not None:
            raw["cedula"] = str(raw["cedula"]).strip()
        if raw.get("edad") is not None:
            raw["edad"] = str(raw["edad"])
        return raw
