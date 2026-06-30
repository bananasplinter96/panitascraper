"""
HospitalesEnVenezuelaSpider — spider for hospitalesenvenezuela.com.
Optimizado para guardar resultados en tiempo real y evitar acumulación en memoria RAM.
"""

import hashlib
import json
import logging
import string
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.items import ScrapedPageItem
from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

SUPABASE_URL = "https://ozuxfepfkvnxkywdsqxy.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im96dXhmZXBma3ZueGt5d2RzcXh5Ii"
    "wicm9sZSI6ImFub24iLCJpYXQiOjE3ODI0MjI5NTEsImV4cCI6MjA5Nzk5ODk1MX0"
    ".YhW0GalGkQZdO2NJTg_01C5XhdMmJ6RbNSNXXC0xG4o"
)
RESULT_CAP = 30
ALPHABET = string.ascii_lowercase
MAX_DEPTH = 7   # safety ceiling
SEED_LEN = 3    # minimum query length accepted by the RPC

_HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _record_key(rec: dict) -> str:
    """Composite dedup key — the RPC returns no unique ID."""
    raw = f"{rec.get('nombre','')}|{rec.get('cedula','')}|{rec.get('centro','')}|{rec.get('registrado','')}"
    return hashlib.md5(raw.encode()).hexdigest()


class HospitalesEnVenezuelaSpider(BaseSpider):
    name = "hospitalesenvenezuela"
    field_map = {
        "nombre":       "nombre",
        "cedula":       "cedula",
        "edad":         None,
        "hospital":     "centro",
        "ciudad":       None,
        "tipo_reporte": "condicion",
        "condicion":    "condicion",
        "estado":       "condicion",
        "notas":        "cama",
    }

    allowed_domains = ["hospitalesenvenezuela.com", "ozuxfepfkvnxkywdsqxy.supabase.co"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.3,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 8,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 8,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo guardamos los hashes únicos para estadísticas, ahorrando RAM
        self._seen: set[str] = set()

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self) -> AsyncIterator:
        # Estadísticas
        yield scrapy.Request(
            f"{SUPABASE_URL}/rest/v1/rpc/estadisticas",
            method="POST",
            body="{}",
            callback=self._parse_stats,
            errback=self.handle_error,
            headers=_HEADERS,
        )
        # Hospitales/centros — direct table read (no RLS)
        yield scrapy.Request(
            f"{SUPABASE_URL}/rest/v1/hospitales"
            "?select=id,nombre,tipo,estado,ciudad,telefono,lat,lng,"
            "estado_operativo,capacidad,nota,confirmaciones,"
            "ultima_actualizacion,verificado,personal_salud"
            "&activo=eq.true",
            callback=self._parse_hospitales,
            errback=self.handle_error,
            headers=_HEADERS,
        )
        # Seed all 3-letter trigrams: aaa … zzz (17,576 peticiones)
        for a in ALPHABET:
            for b in ALPHABET:
                for c in ALPHABET:
                    yield self._buscar_request(a + b + c)

    # ------------------------------------------------------------------
    # Stats & Hospitals
    # ------------------------------------------------------------------

    def _parse_stats(self, response: Response) -> Generator:
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error("Failed to parse estadisticas")
            return
        logger.info("Stats: %s", data)
        yield self.make_item(response, [data])

    def _parse_hospitales(self, response: Response) -> Generator:
        try:
            hospitales = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error("Failed to parse hospitales")
            return
        logger.info("%d hospitales/centros found", len(hospitales))
        yield self.make_item(response, hospitales)

    # ------------------------------------------------------------------
    # Pacientes exhaustion
    # ------------------------------------------------------------------

    def _buscar_request(self, term: str) -> scrapy.Request:
        return scrapy.Request(
            f"{SUPABASE_URL}/rest/v1/rpc/buscar_paciente",
            method="POST",
            body=json.dumps({"p_term": term}),
            callback=self._parse_buscar,
            errback=self._buscar_error,
            headers=_HEADERS,
            meta={"term": term},
            dont_filter=True,
        )

    def _parse_buscar(self, response: Response) -> Generator:
        term: str = response.meta["term"]

        results: list[dict] = []
        if response.status == 200:
            try:
                results = json.loads(response.text)
                if not isinstance(results, list):
                    results = []
            except json.JSONDecodeError:
                logger.error("JSON decode error for term=%r", term)
        else:
            logger.warning("HTTP %d for term=%r", response.status, term)

        # Si hay resultados, los emitimos progresivamente
        if results:
            virtual_url = f"{SUPABASE_URL}/rest/v1/rpc/buscar_paciente?term={term}"
            yield ScrapedPageItem(
                url=virtual_url,
                body=response.body,
                file_type="json",
                spider_name=self.name,
                run_id=self.run_id,
                records=results,
            )

        # Calculamos estadísticas de registros únicos encontrados
        new_count = 0
        for rec in results:
            key = _record_key(rec)
            if key not in self._seen:
                self._seen.add(key)
                new_count += 1

        logger.info("term=%r → %d results, %d new (total unique logged=%d)",
                    term, len(results), new_count, len(self._seen))

        # Si topamos con el límite de 30, expandimos con una letra adicional de forma recursiva
        if len(results) >= RESULT_CAP and len(term) < MAX_DEPTH:
            for c in ALPHABET:
                yield self._buscar_request(term + c)

    def _buscar_error(self, failure) -> Generator:
        term = failure.request.meta.get("term", "?")
        logger.warning("Request failed for term=%r: %s", term, failure.value)

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