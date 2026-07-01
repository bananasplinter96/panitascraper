"""
BusquedaVzlaSheetSpider — spider for the public Google Spreadsheet
"Consolidado Sismo Venezuela 2026".

URL: https://docs.google.com/spreadsheets/d/1bn8BzD_O9rRC3P9ksyAq5iY6MQkQyVxcsSqs7D2xcTM/

Hoja pública compartida con datos de pacientes hospitalizados por hospital.
Exportada como CSV vía el endpoint estándar de Google:

  GET https://docs.google.com/spreadsheets/d/{ID}/export?format=csv&gid={GID}

Contiene 20 pestañas:
  - 1 consolidado general (~3 778 filas, todos los hospitales)
  - 18 pestañas individuales por hospital/centro (~4 600 filas adicionales)
  - 1 pestaña de solo nombres (sin estructura)

Cada pestaña puede tener un esquema ligeramente distinto. El spider
normaliza los campos al conjunto común: n, hospital, apellidos_nombres,
edad, cedula, sexo, telefono, direccion, observaciones, fecha, origen.

El consolidado (gid=2016245006) ya incluye los datos de las otras
pestañas — se descarga primero y se etiqueta como "consolidado".
Las pestañas individuales se descargan también para capturar datos
más recientes que aún no hayan sido agregados al consolidado.
"""

import csv
import io
import logging
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

SHEET_ID = "1bn8BzD_O9rRC3P9ksyAq5iY6MQkQyVxcsSqs7D2xcTM"
EXPORT_BASE = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"

# (label, gid)  — consolidado primero, luego hospitales individuales
# gid=354095182 y gid=1576538018 se omiten: solo contienen nombres sin estructura
SHEETS: list[tuple[str, int]] = [
    ("consolidado",                          2016245006),
    ("hospital_vargas_la_guaira",             150247805),
    ("hospital_universitario_caracas",        364650598),
    ("hospital_sin_nombre",                   421649194),
    ("hospital_general_del_oeste",            600428796),
    ("centro_acopio_caraballeda",             693354603),
    ("hospital_militar_carlos_arvelo",        879681328),
    ("seguro_social_la_guaira",              1039939114),
    ("hospital_ricardo_baquero",             1092888519),
    ("hospital_vargas_heridos",              1333779909),
    ("clinica_el_avila",                     1472531601),
    ("hospital_vargas_de_caracas",           1592380569),
    ("hospital_jose_gregorio_hernandez",     1610526952),
    ("cruz_roja",                            1700332908),
    ("periferico_de_catia",                  1757040189),
    ("hospital_ana_francisca_perez_leon",    1932452863),
    ("hospital_perez_carreno",               2006570672),
    ("hospital_jm_de_los_rios",              2019881375),
    ("hospital_general_vargas",               0),        # gid=0
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
}

# Canonical field mapping from raw CSV header variants
_FIELD_MAP: dict[str, str] = {
    "n°": "n", "num": "n", "nÂ°": "n",
    "hospital": "hospital",
    "apellidos y nombres": "apellidos_nombres",
    "apellido y nombres": "apellidos_nombres",
    "nombre y apellido": "apellidos_nombres",
    "apellidos y nombre": "apellidos_nombres",
    "edad": "edad",
    "cédula / id": "cedula", "cedula / id": "cedula",
    "cã©dula / id": "cedula", "cedula": "cedula",
    "sexo": "sexo",
    "teléfono": "telefono", "telefono": "telefono",
    "telãfono": "telefono",
    "dirección / procedencia": "direccion",
    "direcciãn / procedencia": "direccion",
    "dirección": "direccion", "direcciãn": "direccion",
    "procedencia": "direccion",
    "observaciones": "observaciones", "observaciã³n": "observaciones",
    "parentesco/obs": "observaciones",
    "nota": "observaciones",
    "diagnóstico": "diagnostico", "diagnãstico": "diagnostico",
    "estado": "estado",
    "fecha": "fecha",
    "tab de origen": "origen",
}


def _normalize_key(raw: str) -> str:
    return _FIELD_MAP.get(raw.strip().lower(), raw.strip().lower())


def _parse_sheet_csv(text: str, label: str) -> list[dict]:
    """Parse a hospital sheet CSV, skip title/instruction rows, normalize fields."""
    lines = text.splitlines()

    # Find the header row: first row where most fields are short (< 50 chars)
    # and there are at least 3 non-empty cells
    header_idx = 0
    for i, line in enumerate(lines):
        try:
            fields = next(csv.reader([line]))
        except StopIteration:
            continue
        non_empty = [f for f in fields if f.strip()]
        if len(non_empty) >= 3 and all(len(f) < 60 for f in non_empty):
            header_idx = i
            break

    data_text = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(data_text))
    records = []
    for row in reader:
        normalized = {_normalize_key(k): v.strip() for k, v in row.items() if k}
        # Skip empty rows
        values = [v for v in normalized.values() if v.strip()]
        if not values:
            continue
        normalized["_sheet"] = label
        records.append(normalized)
    return records


class BusquedaVzlaSheetSpider(BaseSpider):
    name = "busquedavzla_sheet"
    field_map = {
        "id":              "_id",
        "nombre":          "apellidos_nombres",
        "cedula":          "cedula",
        "edad":            "edad",
        "sexo":            "sexo",
        "hospital":        "hospital",
        "telefono_familiar": "telefono",
        "ciudad":          "direccion",
        "condicion":       "diagnostico",
        "tipo_reporte":    "estado",
        "estado":          "estado",
        "notas":           "_notas",
    }

    def transform_record(self, raw: dict) -> dict:
        import hashlib as _hl
        nombre = raw.get("apellidos_nombres", "")
        cedula = raw.get("cedula", "")
        sheet = raw.get("_sheet", "")
        key = f"{nombre}:{cedula}:{sheet}"
        raw["_id"] = f"busquedavzla_sheet:{_hl.md5(key.encode()).hexdigest()[:12]}"
        parts = [p for p in (
            raw.get("observaciones"),
            f"Fuente: {raw['origen']}" if raw.get("origen") else None,
        ) if p]
        raw["_notas"] = " | ".join(parts)
        return raw

    allowed_domains = ["docs.google.com"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS": 1,
    }

    async def start(self) -> AsyncIterator:
        for label, gid in SHEETS:
            url = f"{EXPORT_BASE}&gid={gid}"
            yield scrapy.Request(
                url,
                callback=self.parse,
                errback=self.handle_error,
                headers=_HEADERS,
                meta={"label": label, "gid": gid},
                dont_filter=True,
            )

    def parse(self, response: Response, **kwargs) -> Generator:
        label: str = response.meta["label"]
        gid: int = response.meta["gid"]

        if response.status != 200:
            logger.warning("HTTP %d for sheet=%s gid=%d", response.status, label, gid)
            return

        records = self.parse_records(response)
        if not records:
            logger.warning("No records for sheet=%s gid=%d", label, gid)
            return

        self.crawler.stats.inc_value("records_extracted", len(records))
        logger.info("sheet=%s gid=%d → %d records", label, gid, len(records))
        yield self.make_item(response, records)

    def parse_records(self, response: Response) -> list[dict]:
        label = response.meta.get("label", "unknown")
        return _parse_sheet_csv(response.text, label)

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
