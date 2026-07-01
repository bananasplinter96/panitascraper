"""
ReporteVenezuelaSpider — spider for reportevenezuela.com.

Registro SSR (Astro) de 1 145 personas en hospitales y refugios
post-sismo Venezuela 24 jun 2026.

== Mecánica de búsqueda ==
El sitio expone una sola URL de búsqueda:
  GET /buscar?inst={INSTITUCIÓN}&q={PREFIJO}

Reglas:
  - `q` vacío (o ausente) → primeros 25 registros de la institución
  - `q` < 3 caracteres   → 0 resultados (rechazado en cliente y servidor)
  - `q` ≥ 3 caracteres   → word-prefix match: devuelve personas cuyo
      nombre o apellido COMIENZA con ese prefijo. Cap duro = 25.
  - La paginación (page=N, offset=N) es ignorada por el servidor.

== Estrategia de extracción ==
1. Obtener conteos reales de /estadisticas (para saber cuántas buscar).
2. Por cada institución, hacer ?inst=X (sin q) → hasta 25 resultados.
3. Para instituciones con más de 25 registros, iterar sobre ~320
   prefijos de 3 letras comunes en nombres venezolanos/españoles.
   - Si algún prefijo devuelve exactamente 25 (techo) → recursar con
     prefijos de 4 letras (combinando el prefijo + [a-z]).
4. Deduplicar por (nombre, institución).

== Dataset ==
  - 10 instituciones: HOSPITAL DOMINGO LUCIANI (316), PÉREZ CARREÑO (163),
    UNIVERSITARIO CARACAS (148), Refugio Campo de Golf (114),
    J. María Vargas (68), PERIFÉRICO DE CATIA (43),
    Baquero González (31), CRUZ ROJA (27),
    Pérez de León II (7), J.M. de los Ríos (1).
  - Campos: nombre, edad, estado, lugar, cedula (opcional), contacto (opc.)
  - Estado: "Encontrada" / "Buscada" / "Reportado fallecido"
  - Fuente: "oficial" vs "comunidad"
"""

import logging
import re
from html import unescape
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

BASE_URL = "https://reportevenezuela.com"
BUSCAR_URL = f"{BASE_URL}/buscar"
STATS_URL = f"{BASE_URL}/estadisticas"

# Common 3-char word prefixes covering Venezuelan/Spanish surnames and first names.
# Derived from the 500+ most common Venezuelan/Spanish apellidos and given names.
_PREFIXES_3 = [
    # A
    "abi","abo","abr","ach","aco","acr","acu","ace","ado","afl","aga","age","agi","ago","agu",
    "ahl","aim","aja","aje","aji","ajo","aju","alb","alc","ald","ale","alf","alg","alh","ali",
    "alk","all","alm","alo","alp","alq","alr","als","alt","alu","alv","alz","ama","ame","ami",
    "amo","amp","amu","ana","and","ane","ang","ani","ann","ano","ant","any","anz","apa","apo",
    "ara","arc","are","arg","ari","arm","arn","aro","arr","art","arv","arw","arz","asa","ase",
    "asi","asm","asr","ast","asu","ata","ate","ati","ato","atr","atu","atz","ava","ave","avi",
    "avo","avr","avz","aza","aze","azi","azo",
    # B
    "bag","bal","ban","bar","bas","bat","bay","baz","bea","bec","beg","bel","ben","ber","bla",
    "ble","blo","blu","boa","bon","bor","bos","bot","bou","bra","bre","bri","bro","bru","bue",
    "bur","bus",
    # C
    "cab","cac","cad","cag","caj","cal","cam","can","cap","car","cas","cat","cav","caz","ced",
    "cha","che","chi","cho","cid","cil","cin","cis","cla","cli","clo","cob","col","com","con",
    "cor","cos","cot","cou","cov","coz","cri","cru","cua","cub","cue","cul","cum","cup","cur",
    # D
    "dam","dar","dav","del","dia","dib","dif","dig","dom","dor","dua","dub","dug","dur",
    # E
    "ech","ela","ele","elf","eli","elm","elo","els","ema","eme","emi","emp","ena","end","enr",
    "eri","ern","ero","esp","est","evi","evo","ezp",
    # F
    "fab","faj","fal","fan","far","fau","fav","faz","fel","fer","fig","fil","flo","fra","fre",
    "fri","fue","fun","fur",
    # G
    "gal","gam","gan","gar","gaz","geo","gil","gio","gir","gom","gon","gor","gra","gre","gri",
    "gro","gua","gue","gui","gul","gus","gut",
    # H
    "haz","her","hid","hij","hil","hin","hol","hor","hua","hue","hug","hur",
    # I
    "iba","ibr","iga","ige","igi","igo","igu","ili","ima","imi","imo","imp","ina","inm","ino",
    "ins","int","ira","iri","iro","irr","isa","ish","ism","iso","iss","isu",
    # J
    "jar","jav","jer","jim","joh","jon","jor","jos","jua","jul","jun",
    # K
    "kat",
    # L
    "lag","lar","laz","lea","led","leo","ler","les","ley","lim","lin","llo","lob","lon","lop",
    "lor","loz","luc","lui","luj","lun","luz",
    # M
    "mac","mad","mal","man","mar","mas","mat","may","maz","med","mej","mel","men","mer","mil",
    "min","mir","mol","mon","mor","mos","mov","moy","moz","mun",
    # N
    "nar","nat","nav","ner","nie","niv","nog","nor","nut","nua","nun",
    # O
    "oca","oje","ola","olm","oma","ore","orf","org","ori","ork","orm","orp","orr","ort","oru",
    # P
    "pac","pad","pal","par","pas","pat","paz","ped","pen","per","pin","pla","plo","pol","pom",
    "por","pra","pri","pue","pul",
    # Q
    "que","qui",
    # R
    "rab","rad","ram","ran","rav","rea","reg","rei","rej","ren","res","rev","rey","ric","rig",
    "rio","riv","roa","rob","roc","rod","roj","rom","ron","ros","rui","ruz",
    # S
    "sab","sal","sam","san","sar","saz","seb","seg","sel","sem","ser","sil","sim","sir","sol",
    "son","sor","sos","sot","sua","sue","sur",
    # T
    "tam","tap","tar","tej","ten","ter","tim","tob","tom","tor","tov","tra","tri","tru","tuc",
    "tur",
    # U
    "uba","uri","urr","uru",
    # V
    "val","van","var","vas","veg","vel","ven","ver","vil","vir","viv",
    # Y
    "yad","yam","yan","yap","yar","yer","yol","yon",
    # Z
    "zam","zap","zar","zel","zep","zor","zul","zum",
]

INSTITUTIONS = [
    "HOSPITAL DOMINGO LUCIANI",
    "HOSPITAL PÉREZ CARREÑO",
    "HOSPITAL UNIVERSITARIO DE CARACAS",
    "Refugio Campo de Golf Caribe",
    "Hospital Dr. José María Vargas",
    "PERIFÉRICO DE CATIA",
    "Hospital Ricardo Baquero González",
    "CRUZ ROJA",
    "Hospital Pérez de León II",
    "Hospital J.M. de los Ríos",
]

# Institutions known to have > 25 records (need prefix-based deep search)
_LARGE_INSTITUTIONS = {
    "HOSPITAL DOMINGO LUCIANI",
    "HOSPITAL PÉREZ CARREÑO",
    "HOSPITAL UNIVERSITARIO DE CARACAS",
    "Refugio Campo de Golf Caribe",
    "Hospital Dr. José María Vargas",
    "PERIFÉRICO DE CATIA",
    "Hospital Ricardo Baquero González",
    "CRUZ ROJA",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-VE,es;q=0.9,en;q=0.8",
}

# Regex to extract result cards from SSR HTML
_CARD_RE = re.compile(
    r'<section class="tarjeta" aria-label="Resultado: ([^"]+)">(.*?)</section>',
    re.DOTALL,
)
_STATUS_RE = re.compile(r'class="resultado__titulo[^"]*">([^<]+)<')
_SOURCE_RE = re.compile(r'class="sello[^"]*">.*?class="sello__punto"[^/]*/>\s*([^<]+)<', re.DOTALL)
_FIELD_RE = re.compile(
    r'<span class="ficha__k">([^<]+)</span>\s*<span class="ficha__v[^"]*">([^<]+)</span>'
)


def _parse_cards(html: str) -> list[dict]:
    records = []
    for m in _CARD_RE.finditer(html):
        aria_name = unescape(m.group(1))
        card_html = m.group(2)

        status_m = _STATUS_RE.search(card_html)
        status = unescape(status_m.group(1).strip()) if status_m else ""

        source_m = _SOURCE_RE.search(card_html)
        source_raw = source_m.group(1).strip() if source_m else ""
        source_raw = unescape(source_raw)
        # "Fuente oficial · HOSPITAL X"  or  "Comunidad · HOSPITAL X"
        if "·" in source_raw:
            parts = source_raw.split("·", 1)
            source_type = parts[0].strip()
            institution = parts[1].strip()
        else:
            source_type = source_raw
            institution = ""

        fields: dict[str, str] = {}
        for km in _FIELD_RE.finditer(card_html):
            key = unescape(km.group(1).strip().lower())
            val = unescape(km.group(2).strip())
            fields[key] = val

        records.append({
            "nombre": fields.get("nombre", aria_name),
            "edad": fields.get("edad", ""),
            "estado_persona": fields.get("estado", status),
            "lugar": fields.get("lugar", institution),
            "cedula": fields.get("cédula", ""),
            "contacto": fields.get("contacto", ""),
            "estado_busqueda": status,
            "fuente": source_type,
            "institucion": institution,
        })
    return records


class ReporteVenezuelaSpider(BaseSpider):
    name = "reportevenezuela"
    field_map = {
        "id":           "_id",
        "nombre":       "nombre",
        "cedula":       "cedula",
        "edad":         "edad",
        "hospital":     "institucion",
        "tipo_reporte": "estado_busqueda",
        "condicion":    "estado_persona",
        "estado":       "estado_persona",
        "notas":        "_notas",
    }

    @staticmethod
    def _make_id(nombre: str, institucion: str) -> str:
        import hashlib as _hl
        key = f"{nombre.upper()}:{institucion.upper()}"
        return f"reportevenezuela:{_hl.md5(key.encode()).hexdigest()[:12]}"

    def transform_record(self, raw: dict) -> dict:
        raw["_id"] = self._make_id(raw.get("nombre", ""), raw.get("institucion", ""))
        raw["_notas"] = f"{raw.get('fuente', '')} | {raw.get('institucion', '')}".strip(" |")
        return raw

    allowed_domains = ["reportevenezuela.com"]

    custom_settings = {
        "DOWNLOAD_DELAY": 0.8,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 1,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # dedup by (nombre, institucion)
        self._seen: set[tuple[str, str]] = set()
        self._counts: dict[str, int] = {}

    async def start(self) -> AsyncIterator:
        from urllib.parse import urlencode

        # Phase 1: institution-only queries (first 25 alphabetically)
        for inst in INSTITUTIONS:
            yield scrapy.Request(
                f"{BUSCAR_URL}?{urlencode({'inst': inst})}",
                callback=self.parse,
                errback=self.handle_error,
                headers=_HEADERS,
                meta={"inst": inst, "prefix": "", "phase": 1},
                dont_filter=True,
            )

        # Phase 2: prefix sweep for large institutions
        for inst in _LARGE_INSTITUTIONS:
            for prefix in _PREFIXES_3:
                yield scrapy.Request(
                    f"{BUSCAR_URL}?{urlencode({'inst': inst, 'q': prefix})}",
                    callback=self.parse,
                    errback=self.handle_error,
                    headers=_HEADERS,
                    meta={"inst": inst, "prefix": prefix, "phase": 2},
                    dont_filter=True,
                )

    def parse(self, response: Response, **kwargs) -> Generator:
        inst: str = response.meta["inst"]
        prefix: str = response.meta["prefix"]
        phase: int = response.meta["phase"]

        if response.status != 200:
            logger.warning("HTTP %d inst=%s q=%s", response.status, inst, prefix)
            return

        records = self.parse_records(response)
        if not records:
            return

        # Deduplicate
        new_records = []
        for rec in records:
            key = (rec["nombre"].upper(), rec["institucion"].upper())
            if key not in self._seen:
                self._seen.add(key)
                new_records.append(rec)

        if not new_records:
            return

        # If capped (25) in phase 2, recurse with 4-letter prefixes
        if phase == 2 and len(records) == 25 and len(prefix) == 3:
            from urllib.parse import urlencode
            logger.info(
                "CAPPED at 25: inst=%s q=%s — expanding to 4-char prefixes", inst, prefix
            )
            for letter in "abcdefghijklmnopqrstuvwxyz":
                deeper = prefix + letter
                yield scrapy.Request(
                    f"{BUSCAR_URL}?{urlencode({'inst': inst, 'q': deeper})}",
                    callback=self.parse,
                    errback=self.handle_error,
                    headers=_HEADERS,
                    meta={"inst": inst, "prefix": deeper, "phase": 2},
                    dont_filter=True,
                )

        self._counts[inst] = self._counts.get(inst, 0) + len(new_records)
        self.crawler.stats.inc_value("records_extracted", len(new_records))
        logger.info(
            "inst=%s q=%r → %d new (%d total for inst)",
            inst, prefix, len(new_records), self._counts[inst],
        )
        yield self.make_item(response, new_records)

    def parse_records(self, response: Response) -> list[dict]:
        return _parse_cards(response.text)

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
