"""
HospitalesEnVenezuelaSpider — spider for hospitalesenvenezuela.com.

Stack: PWA de un solo archivo HTML + Supabase (PostgREST + RPCs).
La tabla `pacientes` tiene RLS habilitado y no permite lectura directa
con la clave anon. El acceso público es exclusivamente via RPC:

  POST /rest/v1/rpc/buscar_paciente  { "p_term": "<texto>" }
    → array de hasta 30 registros (CONTAINS en nombre y cédula)
    Mínimo de caracteres en p_term: 3.
    Sin paginación ni ID único por registro.

  POST /rest/v1/rpc/estadisticas  {}
    → { pacientes, voluntarios_activos, encontradas, altas }

  GET  /rest/v1/hospitales?select=...&activo=eq.true
    → 292 centros de salud (lectura directa, sin RLS)

Estrategia — exhaustión por trigrams (CONTAINS):
  1. Iterar todos los trigrams aaa..zzz como p_term.
  2. Si resultado == 30 (cap), expandir a quadgrams (trigram + a..z).
  3. Continuar recursivamente hasta MAX_DEPTH.
  4. Deduplicar por clave compuesta (nombre + cedula + centro + registrado).

Dataset: ~34 317 pacientes · 292 hospitales/centros.
Campos: nombre, detalle, cedula, centro, ciudad, telefono, estado,
        estado_por, estado_fecha, registrado, registrado_por,
        vol_nombre, vol_tel, contacto, correcciones,
        zona_rescate, contactado_familiar.
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
    allowed_domains = ["hospitalesenvenezuela.com", "ozuxfepfkvnxkywdsqxy.supabase.co"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.3,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 8,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 8,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._records: dict[str, dict] = {}  # dedup by composite key
        self._pending: int = 0

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
        # Seed all 3-letter trigrams: aaa … zzz
        for a in ALPHABET:
            for b in ALPHABET:
                for c in ALPHABET:
                    self._pending += 1
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

        before = len(self._records)
        for rec in results:
            key = _record_key(rec)
            self._records[key] = rec
        new_count = len(self._records) - before

        logger.debug("term=%r → %d results, %d new (total=%d)",
                     term, len(results), new_count, len(self._records))

        sub_requests: list[scrapy.Request] = []
        if len(results) >= RESULT_CAP and len(term) < MAX_DEPTH:
            for c in ALPHABET:
                sub_requests.append(self._buscar_request(term + c))
            self._pending += len(sub_requests)

        self._pending -= 1

        for req in sub_requests:
            yield req

        if self._pending == 0:
            yield from self._yield_aggregated()

    def _buscar_error(self, failure) -> Generator:
        term = failure.request.meta.get("term", "?")
        logger.warning("Request failed for term=%r: %s", term, failure.value)
        self._pending -= 1
        if self._pending == 0:
            yield from self._yield_aggregated()

    # ------------------------------------------------------------------
    # Final item
    # ------------------------------------------------------------------

    def _yield_aggregated(self) -> Generator:
        records = list(self._records.values())
        if not records:
            logger.warning("No patient records collected")
            return
        logger.info("Exhaustion complete — %d unique patients", len(records))
        self.crawler.stats.set_value("patients_unique", len(records))
        body = json.dumps(records).encode("utf-8")
        yield ScrapedPageItem(
            url=f"{SUPABASE_URL}/rest/v1/rpc/buscar_paciente",
            body=body,
            file_type="json",
            spider_name=self.name,
            run_id=self.run_id,
            records=records,
        )

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
