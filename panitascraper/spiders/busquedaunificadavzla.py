"""
BusquedaUnificadaVzlaSpider — spider for busquedaunificadavzla.com.

El sitio agrega registros de 8 plataformas ciudadanas y expone
un feed de federación público en formato PFIF 1.4 (XML):

  GET /api/pfif?offset=<n>&limit=200
    → XML paginado con <pfif:person> + <pfif:note> anidado.
    El total actual es ~62 780 registros, 200 por página (~314 páginas).
    El total real se lee del comentario HTML en la primera respuesta:
      <!-- ... total=62780. Siguiente página: ?offset=200&limit=200 -->

Nota: el feed NO incluye cédula (PII excluida por diseño).
  Campos: person_record_id, entry_date, author_name, source_name,
          source_url, source_date, full_name, age,
          note.status, note.text.

Dataset: ~62 780 registros de venezuatebusca.com, estoyaquive,
  desaparecidosvenezuela.com, afectadosporelterremotovenezuela.com,
  venezuelareporta.org, vzlanos.com, statusvzla.com, 62.146.225.76:9090.
"""

import logging
import re
from typing import AsyncIterator, Generator
from xml.etree import ElementTree as ET

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

BASE_URL = "https://busquedaunificadavzla.com"
API_URL = f"{BASE_URL}/api/pfif"
PAGE_SIZE = 200
PFIF_NS = "http://zesty.ca/pfif/1.4/"

_HEADERS = {
    "Accept": "application/xml,text/xml",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

_TOTAL_RE = re.compile(r"total=(\d+)")


def _tag(name: str) -> str:
    return f"{{{PFIF_NS}}}{name}"


def _parse_pfif_xml(xml_text: str) -> list[dict]:
    """Parse PFIF 1.4 XML and return list of person dicts."""
    root = ET.fromstring(xml_text)
    records = []
    for person in root.findall(_tag("person")):
        def t(name):
            el = person.find(_tag(name))
            return el.text.strip() if el is not None and el.text else ""

        note = person.find(_tag("note"))
        def nt(name):
            if note is None:
                return ""
            el = note.find(_tag(name))
            return el.text.strip() if el is not None and el.text else ""

        records.append({
            "person_record_id": t("person_record_id"),
            "entry_date": t("entry_date"),
            "source_name": t("source_name"),
            "source_url": t("source_url"),
            "source_date": t("source_date"),
            "full_name": t("full_name"),
            "age": t("age"),
            "photo_url": t("photo_url"),
            "note_status": nt("status"),
            "note_text": nt("text"),
        })
    return records


class BusquedaUnificadaVzlaSpider(BaseSpider):
    name = "busquedaunificadavzla"
    field_map = {
        "id":               "_id",
        "nombre":           "full_name",
        "edad":             "age",
        "foto_url":         "photo_url",
        "tipo_reporte":     "note_status",
        "estado":           "note_status",
        "notas":            "note_text",
        "reportero_nombre": "source_name",
    }

    def transform_record(self, raw: dict) -> dict:
        raw["_id"] = raw.get("person_record_id", "")
        return raw

    allowed_domains = ["busquedaunificadavzla.com"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.5,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 4,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
    }

    async def start(self) -> AsyncIterator:
        yield self._page_request(offset=0)

    def _page_request(self, offset: int) -> scrapy.Request:
        return scrapy.Request(
            f"{API_URL}?offset={offset}&limit={PAGE_SIZE}",
            callback=self.parse,
            errback=self.handle_error,
            headers=_HEADERS,
            meta={"offset": offset},
        )

    def parse(self, response: Response, **kwargs) -> Generator:
        offset: int = response.meta.get("offset", 0)

        if response.status != 200:
            logger.warning("HTTP %d at offset=%d", response.status, offset)
            return

        records = self.parse_records(response)
        if not records:
            logger.info("No records at offset=%d — done", offset)
            return

        self.crawler.stats.inc_value("records_extracted", len(records))
        logger.info("offset=%d → %d records", offset, len(records))
        yield self.make_item(response, records)

        # Read total from XML comment on first page to log progress
        if offset == 0:
            m = _TOTAL_RE.search(response.text)
            if m:
                total = int(m.group(1))
                logger.info("Total records reported by API: %d", total)
                self.crawler.stats.set_value("records_total_reported", total)

        # Continue if a full page was returned
        if len(records) == PAGE_SIZE:
            yield self._page_request(offset=offset + PAGE_SIZE)

    def parse_records(self, response: Response) -> list[dict]:
        try:
            return _parse_pfif_xml(response.text)
        except ET.ParseError as e:
            logger.error("XML parse error at offset=%s: %s",
                         response.meta.get("offset"), e)
            return []

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
