"""
HospitalesDeVenezuelaSpider — spider for hospitalesdevenezuela.com.

Next.js 15 App Router con Turbopack. Sin API REST pública.
Los datos de pacientes se entregan como React Server Components (RSC)
en formato text/x-component — una stream de líneas donde la línea más
larga embebe el array `people` de cada hospital en JSON.

Estrategia:
  1. GET /hospitales  (HTML)
     → extrae los 94 IDs de hospital del HTML renderizado.
  2. GET /hospitales/{id}  con cabecera `RSC: 1`
     → respuesta text/x-component; parsear la línea más larga
       con regex para extraer objetos {"id":...,"firstName":...}.
  3. Yield un item por hospital con sus registros.

Dataset: ~94 hospitales/centros · personas a confirmar (≥295 en el más grande).
Campos por registro: id, firstName, lastName, age, idNumber,
  foundLocation, currentHospital, notes, hospital (name/location/type),
  redacted.
"""

import json
import logging
import re
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

BASE_URL = "https://hospitalesdevenezuela.com"

_HTML_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

_RSC_HEADERS = {
    **_HTML_HEADERS,
    "Accept": "text/x-component",
    "RSC": "1",
}

# Match full person objects embedded in the RSC stream
_PERSON_RE = re.compile(
    r'\{"id":"(cm[a-z0-9]+)","firstName":[^{]*?"redacted":(true|false)\}'
)


def _extract_people(rsc_body: str) -> list[dict]:
    """Extract person records from a RSC text/x-component response."""
    # The patient data lives in the longest line of the RSC stream
    longest = max(rsc_body.splitlines(), key=len, default="")

    records: list[dict] = []
    for match in _PERSON_RE.finditer(longest):
        raw = match.group(0)
        try:
            # hospital field sometimes contains a back-reference string;
            # replace it with null to keep valid JSON
            cleaned = re.sub(r'"hospital":"[^"]{10,}"', '"hospital":null', raw)
            obj = json.loads(cleaned)
            records.append(obj)
        except json.JSONDecodeError:
            pass
    return records


_FALLECIDO_KEYWORDS = {"fallecido", "fallecida", "deceased", "obito", "exitus"}
_INGRESADO_KEYWORDS = {"alta", "hospitalizado", "uci", "estable", "grave", "ingreso", "ingresado"}


class HospitalesDeVenezuelaSpider(BaseSpider):
    name = "hospitalesdevenezuela"
    allowed_domains = ["hospitalesdevenezuela.com"]

    field_map = {
        "id":           "_id",
        "nombre":       "_nombre",
        "edad":         "age",
        "cedula":       "idNumber",
        "hospital":     "_hospital",
        "ciudad":       "_ciudad",
        "condicion":    "_condicion",
        "tipo_reporte": "_tipo_reporte",
        "notas":        "_notas",
    }

    def transform_record(self, raw: dict) -> dict:
        raw["_id"] = f"hospitalesvzla:{raw.get('id', '')}"
        first = (raw.get("firstName") or "").strip()
        last  = (raw.get("lastName") or "").strip()
        raw["_nombre"] = f"{first} {last}".strip()

        hosp = raw.get("hospital") or {}
        raw["_hospital"] = raw.get("currentHospital") or (hosp.get("name") if isinstance(hosp, dict) else "")
        raw["_ciudad"]   = raw.get("foundLocation") or (hosp.get("location") if isinstance(hosp, dict) else "")

        notes_raw = (raw.get("notes") or "").strip()
        notes_lower = notes_raw.lower()
        if any(kw in notes_lower for kw in _FALLECIDO_KEYWORDS):
            raw["_tipo_reporte"] = "fallecido"
            raw["_condicion"] = notes_raw
            raw["_notas"] = ""
        elif any(kw in notes_lower for kw in _INGRESADO_KEYWORDS):
            raw["_tipo_reporte"] = "ingresado"
            raw["_condicion"] = notes_raw
            raw["_notas"] = ""
        else:
            raw["_tipo_reporte"] = ""
            raw["_condicion"] = ""
            raw["_notas"] = notes_raw
        return raw

    custom_settings = {
        "DOWNLOAD_DELAY": 0.5,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 4,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
    }

    # ------------------------------------------------------------------
    # Startup — scrape hospital list
    # ------------------------------------------------------------------

    async def start(self) -> AsyncIterator:
        yield scrapy.Request(
            f"{BASE_URL}/hospitales",
            callback=self._parse_hospital_list,
            errback=self.handle_error,
            headers=_HTML_HEADERS,
        )

    def _parse_hospital_list(self, response: Response) -> Generator:
        # Hospital IDs are CUID slugs in /hospitales/<id> hrefs
        ids = list(dict.fromkeys(
            re.findall(r'/hospitales/(cm[a-z0-9]{20,30})', response.text)
        ))
        logger.info("Found %d hospital IDs", len(ids))
        for hid in ids:
            yield scrapy.Request(
                f"{BASE_URL}/hospitales/{hid}",
                callback=self._parse_hospital_rsc,
                errback=self.handle_error,
                headers=_RSC_HEADERS,
                meta={"hospital_id": hid},
            )

    # ------------------------------------------------------------------
    # Per-hospital RSC page
    # ------------------------------------------------------------------

    def _parse_hospital_rsc(self, response: Response) -> Generator:
        hospital_id: str = response.meta["hospital_id"]

        if response.status != 200:
            logger.warning("HTTP %d for hospital %s", response.status, hospital_id)
            return

        people = _extract_people(response.text)

        if not people:
            logger.warning("No people extracted for hospital %s", hospital_id)
            return

        self.crawler.stats.inc_value("records_extracted", len(people))
        logger.info("Hospital %s → %d records", hospital_id, len(people))

        yield self.make_item(response, people)

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    def parse_records(self, response: Response) -> list[dict]:
        return _extract_people(response.text)

    def parse(self, response: Response, **kwargs) -> Generator:
        yield from self._parse_hospital_rsc(response)

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
