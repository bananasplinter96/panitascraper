import logging
from typing import Any

from itemadapter import ItemAdapter
from sqlalchemy import text
from sqlalchemy.orm import Session

from models import get_engine

logger = logging.getLogger(__name__)

DEFAULT_STATUS_MAP: dict[str, str] = {
    "ingresado": "ingresado", "hospitalizado": "ingresado", "hospitalized": "ingresado",
    "admitido": "ingresado", "en tratamiento": "ingresado", "internado": "ingresado",
    "fallecido": "fallecido", "deceased": "fallecido", "muerto": "fallecido",
    "óbito": "fallecido", "exitus": "fallecido",
    "desaparecido": "desaparecido", "missing": "desaparecido", "no localizado": "desaparecido",
    "transferido": "ingresado", "trasladado": "ingresado", "egresado": "ingresado", "alta": "ingresado",
}

PERSONA_COLUMNS = {"nombre", "cedula", "edad", "tipo_reporte", "hospital", "ciudad", "condicion", "estado", "notas"}


class TransformPipeline:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(database_url=crawler.settings.get("DATABASE_URL"))

    def open_spider(self, spider):
        self.engine = get_engine(self.database_url)

    def close_spider(self, spider):
        if self.engine:
            self.engine.dispose()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        if not adapter.get("is_new", True):
            return item

        records: list[dict] = adapter.get("records", [])
        if not records:
            return item

        field_map = getattr(spider, "field_map", {})
        status_map = {**DEFAULT_STATUS_MAP, **getattr(spider, "status_map", {})}
        run_id = adapter.get("run_id", "")
        source_url = adapter.get("url", "")

        for raw in records:
            if hasattr(spider, "transform_record"):
                raw = spider.transform_record(raw)
            persona = self._map_fields(raw, field_map)
            persona = self._normalize_status(persona, status_map)
            persona = self._add_provenance(persona, source_url, run_id)
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

    def _normalize_status(self, persona: dict, status_map: dict) -> dict:
        raw_status = persona.get("tipo_reporte", "")
        persona["tipo_reporte"] = status_map.get(raw_status.lower(), "ingresado")
        if "estado" not in persona:
            persona["estado"] = persona["tipo_reporte"].capitalize()
        return persona

    def _add_provenance(self, persona: dict, url: str, run_id: str) -> dict:
        existing = persona.get("notas", "")
        prov = f"Fuente: {url} | Run: {run_id}"
        persona["notas"] = f"{existing}; {prov}".lstrip("; ") if existing else prov
        return persona

    def _upsert_persona(self, persona: dict) -> None:
        if not persona.get("nombre") and not persona.get("cedula"):
            return
        safe = {k: v for k, v in persona.items() if k in PERSONA_COLUMNS}
        if not safe:
            return

        with Session(self.engine) as session:
            try:
                cedula = persona.get("cedula", "").strip()
                nombre = persona.get("nombre", "").strip()
                hospital = persona.get("hospital", "").strip()
                existing_id = None

                if cedula:
                    row = session.execute(text("SELECT id FROM personas WHERE cedula = :c LIMIT 1"), {"c": cedula}).fetchone()
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
                    set_clauses = ", ".join(f"{col} = :{col}" for col in safe) + ", updated_at = NOW()"
                    session.execute(text(f"UPDATE personas SET {set_clauses} WHERE id = :id"), {**safe, "id": existing_id})
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
