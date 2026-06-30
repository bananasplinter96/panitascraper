"""
DriveSismoVzlaSpider — spider for the Google Drive folder "SISMO 2026 VZLA".

Carpeta pública: https://drive.google.com/drive/folders/1o36ifaRz45kAs5rKzci49aD0mP5JB_YI

Contiene múltiples subcarpetas de hospitales con imágenes JPG de listas
físicas (no scrapeable sin OCR) y tres archivos de datos estructurados
accesibles como CSV vía el endpoint de exportación de Google:

  GET https://docs.google.com/spreadsheets/d/{ID}/export?format=csv[&gid={GID}]

Archivos con datos estructurados:

1. CONSOLIDADO GENERAL (Excel → exportado como CSV)
   ID: 15gUXyoBjsZK8RlixGotv635uY4t1m5Wu
   ~3 689 filas · campos: APELLIDO(S), NOMBRE(S), CÉDULA/ID, EDAD, ¿MENOR?,
   SEXO, HOSPITAL/CENTRO, ÁREA/ZONA, PISO/CAMA, PROCEDENCIA,
   DIAGNÓSTICO/SERVICIO, ESTADO/CONDICIÓN, FECHA REG., HORA,
   FAMILIAR, FUENTE, COMENTARIOS

2. 01-LISTA DIGITALIZADA PACIENTES (Google Sheet)
   ID: 1wzpm_7pd0fC4hFou5FzppMNeZkd6J6NvrPqy-PWNvRY
   ~213 filas · campos: Apellido, Nombre, Cedula, Edad, Sexo, Procedencia,
   Centro donde se encuentra, Observaciones, Fecha de actualización, Hora

3. HOSPITAL VARGAS DE CARACAS (Google Sheet, datos OCR)
   ID: 1IcuwWYo2iMK1GF3M_QmA3BEEkKKKtyDJfQW2KRPhZeg
   ~226 filas · campos: archivos, id, cedula, nombre_final, nombre_ocr,
   confianza_max, apariciones, verificado_cne, coincide_ocr, nombre_cne,
   primer_apellido, segundo_apellido, primer_nombre, segundo_nombre,
   estado, municipio, parroquia

Las subcarpetas de hospital (JOSE GREGORIO H, PEREZ CARREÑO, DE CATIA,
EL AVILA, VARGAS) contienen únicamente imágenes JPG de listas físicas
y no se procesan aquí.
"""

import csv
import io
import logging
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

_EXPORT_BASE = "https://docs.google.com/spreadsheets/d/{id}/export?format=csv"

# (label, sheet_id, gid or None)
_SHEETS: list[tuple[str, str, str | None]] = [
    (
        "consolidado",
        "15gUXyoBjsZK8RlixGotv635uY4t1m5Wu",
        None,
    ),
    (
        "lista_digitalizada",
        "1wzpm_7pd0fC4hFou5FzppMNeZkd6J6NvrPqy-PWNvRY",
        None,
    ),
    (
        "hospital_vargas_ocr",
        "1IcuwWYo2iMK1GF3M_QmA3BEEkKKKtyDJfQW2KRPhZeg",
        None,
    ),
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
}


def _parse_csv(text: str) -> list[dict]:
    """Parse CSV text, skipping instruction/blank rows at the top."""
    lines = text.splitlines()

    # Find the actual header row — first row where most fields are non-empty
    # and look like column names (not instruction sentences)
    header_idx = 0
    for i, line in enumerate(lines):
        fields = next(csv.reader([line]))
        non_empty = sum(1 for f in fields if f.strip())
        # A real header has ≥3 non-empty short fields
        if non_empty >= 3 and all(len(f) < 60 for f in fields if f.strip()):
            header_idx = i
            break

    data_lines = lines[header_idx:]
    reader = csv.DictReader(io.StringIO("\n".join(data_lines)))
    records = []
    for row in reader:
        # Skip completely empty rows
        if any(v.strip() for v in row.values()):
            records.append({k.strip(): v.strip() for k, v in row.items() if k})
    return records


class DriveSismoVzlaSpider(BaseSpider):
    name = "drive_sismo_vzla"
    field_map = {
        "nombre":       "APELLIDO(S)",
        "cedula":       "CEDULA/ID",
        "edad":         "EDAD",
        "hospital":     "HOSPITAL/CENTRO",
        "ciudad":       "AREA/ZONA",
        "tipo_reporte": "ESTADO/CONDICION",
        "condicion":    "DIAGNOSTICO/SERVICIO",
        "estado":       "ESTADO/CONDICION",
        "notas":        "COMENTARIOS",
    }

    def transform_record(self, raw: dict) -> dict:
        # Unifica clave con y sin acentos (CSV llega con encoding variable)
        for src, dst in [
            ("APELLIDO(S)", "APELLIDO(S)"),
            ("NOMBRE(S)", "NOMBRE(S)"),
        ]:
            pass
        apellidos = raw.get("APELLIDO(S)", raw.get("APELLIDOS", "")).strip()
        nombres   = raw.get("NOMBRE(S)",   raw.get("NOMBRES", "")).strip()
        if apellidos and nombres:
            raw["APELLIDO(S)"] = f"{apellidos} {nombres}"
        elif nombres:
            raw["APELLIDO(S)"] = nombres
        # Normalise cedula key variants
        for k in list(raw):
            if "cedula" in k.lower() or "cédula" in k.lower() or "cedula" in k.lower():
                raw["CEDULA/ID"] = raw.get("CEDULA/ID") or raw[k]
        return raw

    allowed_domains = ["docs.google.com", "drive.google.com"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS": 1,
    }

    async def start(self) -> AsyncIterator:
        for label, sheet_id, gid in _SHEETS:
            url = _EXPORT_BASE.format(id=sheet_id)
            if gid:
                url += f"&gid={gid}"
            yield scrapy.Request(
                url,
                callback=self.parse,
                errback=self.handle_error,
                headers=_HEADERS,
                meta={"label": label, "sheet_id": sheet_id},
                # Google redirects CSV exports — allow following
                dont_filter=True,
            )

    def parse(self, response: Response, **kwargs) -> Generator:
        label: str = response.meta["label"]

        if response.status != 200:
            logger.warning("HTTP %d for sheet=%s", response.status, label)
            return

        records = self.parse_records(response)
        if not records:
            logger.warning("No records parsed for sheet=%s", label)
            return

        self.crawler.stats.inc_value("records_extracted", len(records))
        logger.info("sheet=%s → %d records", label, len(records))
        yield self.make_item(response, records)

    def parse_records(self, response: Response) -> list[dict]:
        return _parse_csv(response.text)

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
