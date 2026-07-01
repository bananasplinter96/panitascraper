import hashlib
import logging
from typing import Any

from itemadapter import ItemAdapter
from sqlalchemy import text
from sqlalchemy.orm import Session

from models import get_engine

logger = logging.getLogger(__name__)

DEFAULT_STATUS_MAP: dict[str, str] = {
    # ingresado — actualmente hospitalizado / en tratamiento
    "ingresado": "ingresado", "hospitalizado": "ingresado", "hospitalized": "ingresado",
    "admitido": "ingresado", "admitted": "ingresado", "en tratamiento": "ingresado",
    "internado": "ingresado", "transferido": "ingresado", "trasladado": "ingresado",
    "atendido": "ingresado", "atendida": "ingresado",
    # dado_de_alta — salió del hospital / fue localizado con vida
    "egresado": "dado_de_alta", "alta": "dado_de_alta", "dado de alta": "dado_de_alta",
    "discharged": "dado_de_alta", "found": "dado_de_alta", "localizado": "dado_de_alta",
    "encontrado": "dado_de_alta", "encontrada": "dado_de_alta",
    "aparecido": "dado_de_alta", "aparecida": "dado_de_alta",
    "reunited": "dado_de_alta", "believed_alive": "dado_de_alta",
    # fallecido
    "fallecido": "fallecido", "fallecida": "fallecido", "deceased": "fallecido",
    "muerto": "fallecido", "muerta": "fallecido", "óbito": "fallecido",
    "exitus": "fallecido", "believed_dead": "fallecido", "reportado fallecido": "fallecido",
    # desaparecido
    "desaparecido": "desaparecido", "desaparecida": "desaparecido",
    "missing": "desaparecido", "no localizado": "desaparecido",
    "sin_contacto": "desaparecido", "buscando": "desaparecido",
    "sincontacto": "desaparecido", "believed_missing": "desaparecido",
    "search": "desaparecido", "buscada": "desaparecido", "buscado": "desaparecido",
}

SEXO_MAP: dict[str, str] = {
    "m": "Masculino", "masculino": "Masculino", "male": "Masculino", "hombre": "Masculino",
    "f": "Femenino", "femenino": "Femenino", "female": "Femenino", "mujer": "Femenino",
}

def puede_actualizar_estado(actual: str | None, nuevo: str | None) -> bool:
    """
    Matriz de prioridad de transición de estado. Evita que una importación
    (manual o de un spider) degrade o corrompa el estado de una persona:

      - fallecido            -> nunca se toca (requiere revisión manual)
      - desaparecido         -> siempre se puede actualizar (cualquier dato ayuda)
      - ingresado/dado_de_alta -> NO se puede volver a desaparecido (regresión inválida)
      - cualquier otra combinación (ingresado<->dado_de_alta<->fallecido) -> se permite
    """
    if not actual:
        return True
    if actual == "fallecido":
        return False
    if actual == "desaparecido":
        return True
    if nuevo == "desaparecido":
        return False
    return True


PERSONA_COLUMNS = {
    "id", "tipo_reporte", "nombre", "edad", "cedula", "sexo", "foto_url",
    "hospital", "ciudad", "cama_sala", "condicion", "contacto_familiar",
    "ubicacion_cuerpo", "confirmacion_tipo", "confirmacion_detalle",
    "ultimo_lugar", "ultimo_contacto", "descripcion_fisica", "telefono_familiar",
    "reportero_nombre", "reportero_telefono", "estado", "notas",
    "spider_name", "fuente_url",
}


class TransformPipeline:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None

    @classmethod
    def from_crawler(cls, crawler):
        o = cls(database_url=crawler.settings.get("DATABASE_URL"))
        o.crawler = crawler
        return o

    def open_spider(self):
        self.engine = get_engine(self.database_url)

    def close_spider(self):
        if self.engine:
            self.engine.dispose()

    def process_item(self, item):
        adapter = ItemAdapter(item)
        if not adapter.get("is_new", True):
            return item

        records: list[dict] = adapter.get("records", [])
        if not records:
            return item

        spider = self.crawler.spider
        field_map = getattr(spider, "field_map", {})
        status_map = {**DEFAULT_STATUS_MAP, **getattr(spider, "status_map", {})}
        source_url = adapter.get("url", "")

        for raw in records:
            if hasattr(spider, "transform_record"):
                raw = spider.transform_record(raw)
            persona = self._map_fields(raw, field_map)
            persona = self._normalize(persona, status_map, spider, source_url)
            self._upsert_persona(persona)

        return item

    def _map_fields(self, raw: dict, field_map: dict) -> dict:
        persona: dict[str, Any] = {}
        for col, src in field_map.items():
            if src is None:
                continue
            value = raw.get(src)
            if value is not None and str(value).strip():
                persona[col] = str(value).strip()
        return persona

    def _normalize(self, persona: dict, status_map: dict, spider, source_url: str) -> dict:
        # tipo_reporte
        raw_status = persona.get("tipo_reporte", "")
        persona["tipo_reporte"] = status_map.get(raw_status.lower(), "desaparecido")
        if "estado" not in persona:
            persona["estado"] = persona["tipo_reporte"].capitalize()

        # sexo
        if "sexo" in persona:
            persona["sexo"] = SEXO_MAP.get(persona["sexo"].lower(), persona["sexo"])

        # foto_url: drop base64 data URIs
        if persona.get("foto_url", "").startswith("data:"):
            del persona["foto_url"]

        # provenance
        persona["spider_name"] = spider.name
        persona["fuente_url"] = persona.get("fuente_url") or source_url

        # id: generate stable hash if not provided by spider
        if not persona.get("id"):
            id_src = f"{spider.name}:{persona.get('nombre', '')}:{persona.get('cedula', '')}"
            persona["id"] = f"{spider.name}:{hashlib.md5(id_src.encode()).hexdigest()[:12]}"

        return persona

    def _upsert_persona(self, persona: dict) -> None:
        if not persona.get("nombre") and not persona.get("cedula"):
            return
        safe = {k: v for k, v in persona.items() if k in PERSONA_COLUMNS}
        if not safe:
            return

        with Session(self.engine) as session:
            try:
                provided_id = safe.get("id")
                cedula = (safe.get("cedula") or "").strip()
                nombre = (safe.get("nombre") or "").strip()
                hospital = (safe.get("hospital") or "").strip()
                existing_id = None

                # Lookup order: provided id → cedula → nombre+hospital
                if provided_id:
                    row = session.execute(
                        text("SELECT id FROM personas WHERE id = :i LIMIT 1"), {"i": provided_id}
                    ).fetchone()
                    if row:
                        existing_id = row[0]

                if not existing_id and cedula:
                    row = session.execute(
                        text("SELECT id FROM personas WHERE cedula = :c LIMIT 1"), {"c": cedula}
                    ).fetchone()
                    if row:
                        existing_id = row[0]

                if not existing_id and nombre and hospital:
                    row = session.execute(
                        text("SELECT id FROM personas WHERE nombre ILIKE :n AND hospital ILIKE :h LIMIT 1"),
                        {"n": nombre, "h": hospital},
                    ).fetchone()
                    if row:
                        existing_id = row[0]

                if existing_id:
                    actual_row = session.execute(
                        text("SELECT tipo_reporte FROM personas WHERE id = :id"), {"id": existing_id}
                    ).fetchone()
                    actual_tipo = actual_row[0] if actual_row else None
                    nuevo_tipo = safe.get("tipo_reporte")

                    if not puede_actualizar_estado(actual_tipo, nuevo_tipo):
                        logger.info(
                            "Transición de estado bloqueada (%s -> %s) para id=%s",
                            actual_tipo, nuevo_tipo, existing_id,
                        )
                    else:
                        update_safe = {k: v for k, v in safe.items() if k != "id"}
                        if update_safe:
                            set_clauses = ", ".join(f"{col} = :{col}" for col in update_safe) + ", updated_at = NOW()"
                            session.execute(
                                text(f"UPDATE personas SET {set_clauses} WHERE id = :id"),
                                {**update_safe, "id": existing_id},
                            )
                else:
                    cols = ", ".join(safe.keys())
                    vals = ", ".join(f":{k}" for k in safe)
                    session.execute(
                        text(f"INSERT INTO personas ({cols}, created_at, updated_at) VALUES ({vals}, NOW(), NOW()) ON CONFLICT DO NOTHING"),
                        safe,
                    )
                session.commit()
            except Exception as exc:
                session.rollback()
                logger.error("Failed to upsert persona: %s | data=%s", exc, persona)
