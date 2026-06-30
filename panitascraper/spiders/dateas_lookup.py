"""
DateasLookupSpider — enriquecimiento de cédulas contra dateas.com.

dateas.com publica datos del Registro Electoral del CNE venezolano
(Consejo Nacional Electoral, art. 27 Ley Orgánica de Procesos Electorales).
Para cada cédula conocida de nuestras bases consolidadas, este spider
obtiene la información oficial: nombre completo, fecha de nacimiento y
ubicación (estado, municipio, parroquia).

== Uso ==
  # Desde un archivo (una cédula por línea):
  scrapy crawl dateas_lookup -a cedulas_file=/ruta/cedulas.txt

  # Desde argumento directo (separadas por coma):
  scrapy crawl dateas_lookup -a cedulas=10001561,11410534,7654321

== Flujo por cédula ==
  1. POST /es/consulta_venezuela  {cedula=X, name=}
     → tabla con filas <tr class="odd|even"> si hay resultados
     → extrae slug del primer resultado (puede haber varios homónimos)
  2. GET /es/persona_venezuela/{slug}
     → página de detalle con nombre, fecha_nacimiento, ubicación
     → datos libres del CNE, sin login

== Campos del item resultante ==
  cedula_input       : cédula tal como fue consultada
  found              : true | false (no está en la base del CNE)
  nombre             : nombre completo en mayúsculas
  cedula_formateada  : cédula con puntos (e.g. "10.001.561")
  fecha_nacimiento   : DD/MM/YYYY
  ubicacion          : texto completo de la ubicación
  estado             : estado venezolano
  municipio          : municipio
  parroquia          : parroquia (si se puede parsear de ubicacion)
  detail_url         : URL del perfil en dateas.com
  resultados_total   : cuántos resultados devolvió la búsqueda (≥1)

== Notas ==
  - Tasa: 1 req/s. dateas.com no tiene rate-limit explícito pero
    las IPs pueden ser bloqueadas si se abusa.
  - Si la búsqueda devuelve múltiples registros (mismo número de CI
    en distintas personas — raro), se enriquece sólo el primero y
    se registra el total en resultados_total.
  - Cédulas sin resultado (not found) generan un item con found=False
    para mantener trazabilidad completa.
"""

import logging
import re
from pathlib import Path
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import FormRequest, Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.dateas.com/es/consulta_venezuela"
DETAIL_BASE = "https://www.dateas.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-VE,es;q=0.9,en;q=0.8",
    "Referer": "https://www.dateas.com/es/public-search/personas_venezuela/venezuela",
    "Origin": "https://www.dateas.com",
}

_ROW_RE = re.compile(
    r'<tr class="(?:odd|even)">(.*?)</tr>',
    re.DOTALL,
)
_SLUG_RE = re.compile(r'href="/es/persona_venezuela/([^"]+)"')
_NAME_RE = re.compile(r'data-label="Nombre"[^>]*><a[^>]*>([^<]+)<')
_LOC_RE = re.compile(r'data-label="Ubicaci[oó]n"[^>]*>([^<]+)<')

# Detail page patterns
_DETAIL_CEDULA_RE = re.compile(r'[Cc][eé]dula\s*</[^>]+>\s*<[^>]+>([^<]+)<')
_DETAIL_DOB_RE = re.compile(
    r'(?:Fecha de Nacimiento|Nacimiento)\s*</[^>]+>\s*<[^>]+>([^<]+)<'
)
_DETAIL_LOCATION_RE = re.compile(
    r'[Uu]bicaci[oó]n\s*</[^>]+>\s*<[^>]+>([^<]+)<'
)
_DETAIL_NAME_RE = re.compile(r'<h1[^>]*>\s*([^<]+)\s*</h1>')


def _parse_location(raw: str) -> dict:
    """Split 'Cm. Pariaguan, Miranda, Edo. Anzoategui' into parts."""
    parts = [p.strip() for p in raw.split(",")]
    result = {"ubicacion": raw, "parroquia": "", "municipio": "", "estado": ""}
    if len(parts) >= 3:
        result["parroquia"] = parts[0]
        result["municipio"] = parts[1]
        result["estado"] = parts[-1]
    elif len(parts) == 2:
        result["municipio"] = parts[0]
        result["estado"] = parts[1]
    elif len(parts) == 1:
        result["estado"] = parts[0]
    return result


class DateasLookupSpider(BaseSpider):
    name = "dateas_lookup"
    allowed_domains = ["www.dateas.com"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.2,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 1,
    }

    def __init__(self, cedulas: str = "", cedulas_file: str = "", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cedulas: list[str] = []

        if cedulas_file:
            path = Path(cedulas_file)
            if path.exists():
                self._cedulas = [
                    line.strip()
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip().isdigit()
                ]
                logger.info("Loaded %d cedulas from %s", len(self._cedulas), cedulas_file)
            else:
                logger.error("cedulas_file not found: %s", cedulas_file)

        if cedulas:
            extra = [c.strip() for c in cedulas.split(",") if c.strip().isdigit()]
            self._cedulas.extend(extra)

        if not self._cedulas:
            logger.warning(
                "No cedulas provided. Use -a cedulas=X,Y or -a cedulas_file=/path/file.txt"
            )

    async def start(self) -> AsyncIterator:
        for ci in self._cedulas:
            # Strip dots/dashes in case cedulas come formatted
            ci_clean = re.sub(r"[.\-]", "", ci)
            yield FormRequest(
                SEARCH_URL,
                formdata={"cedula": ci_clean, "name": ""},
                callback=self._parse_search,
                errback=self.handle_error,
                headers=_HEADERS,
                meta={"cedula_input": ci_clean},
                dont_filter=True,
            )

    def _parse_search(self, response: Response) -> Generator:
        ci = response.meta["cedula_input"]

        if response.status != 200:
            logger.warning("HTTP %d for cedula=%s", response.status, ci)
            yield self.make_item(response, [{"cedula_input": ci, "found": False, "error": f"HTTP {response.status}"}])
            return

        rows = _ROW_RE.findall(response.text)
        if not rows:
            logger.info("cedula=%s → not found in dateas", ci)
            yield self.make_item(response, [{"cedula_input": ci, "found": False}])
            return

        total = len(rows)
        first_row = rows[0]
        slug_m = _SLUG_RE.search(first_row)
        name_m = _NAME_RE.search(first_row)
        loc_m = _LOC_RE.search(first_row)

        if not slug_m:
            logger.warning("cedula=%s → row found but no slug", ci)
            yield self.make_item(response, [{"cedula_input": ci, "found": False, "error": "no slug"}])
            return

        slug = slug_m.group(1)
        partial = {
            "cedula_input": ci,
            "found": True,
            "nombre": name_m.group(1).strip() if name_m else "",
            "ubicacion_search": loc_m.group(1).strip() if loc_m else "",
            "resultados_total": total,
            "detail_url": f"{DETAIL_BASE}/es/persona_venezuela/{slug}",
        }

        # Fetch detail page for dob + full location
        yield scrapy.Request(
            partial["detail_url"],
            callback=self._parse_detail,
            errback=self.handle_error,
            headers=_HEADERS,
            meta={"cedula_input": ci, "partial": partial},
            dont_filter=True,
        )

    def _parse_detail(self, response: Response) -> Generator:
        ci = response.meta["cedula_input"]
        partial: dict = response.meta["partial"]

        if response.status != 200:
            logger.warning("Detail HTTP %d for cedula=%s", response.status, ci)
            yield self.make_item(response, [partial])
            return

        text = response.text

        name_m = _DETAIL_NAME_RE.search(text)
        dob_m = _DETAIL_DOB_RE.search(text)
        loc_m = _DETAIL_LOCATION_RE.search(text)
        ced_m = _DETAIL_CEDULA_RE.search(text)

        nombre = name_m.group(1).strip() if name_m else partial.get("nombre", "")
        dob = dob_m.group(1).strip() if dob_m else ""
        raw_loc = loc_m.group(1).strip() if loc_m else partial.get("ubicacion_search", "")
        cedula_fmt = ced_m.group(1).strip() if ced_m else ""

        loc_parts = _parse_location(raw_loc)

        record = {
            "cedula_input": ci,
            "found": True,
            "nombre": nombre,
            "cedula_formateada": cedula_fmt,
            "fecha_nacimiento": dob,
            "resultados_total": partial.get("resultados_total", 1),
            "detail_url": partial["detail_url"],
            **loc_parts,
        }

        logger.info("cedula=%s → %s | %s | %s", ci, nombre, dob, raw_loc)
        self.crawler.stats.inc_value("cedulas_found")
        yield self.make_item(response, [record])

    def parse_records(self, response: Response) -> list[dict]:
        return []

    def handle_error(self, failure):
        ci = failure.request.meta.get("cedula_input", "?")
        logger.error("Request failed cedula=%s: %s", ci, failure.value)
        self.crawler.stats.inc_value("request_errors")

    def parse(self, response: Response, **kwargs) -> Generator:
        pass
