import json

from .base import persona, s


PFIF_STATUS_MAP = {
    "believed_alive": "ingresado",
    "believed_missing": "desaparecido",
    "believed_dead": "fallecido",
    "information_sought": "desaparecido",
}


def parse(raw: bytes, url: str = "") -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace")
    data = json.loads(text)
    items = data if isinstance(data, list) else [data]
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "full_name" not in item:
            continue
        status = s(item.get("status"))
        tipo = PFIF_STATUS_MAP.get(status, "ingresado")
        p = persona(
            id=f"ubicame:{item.get('person_record_id', '')}",
            nombre=item.get("full_name"),
            spider_name="ubicame",
            fuente_url=url,
            tipo_reporte=tipo,
            edad=item.get("age"),
            cedula=item.get("ext_venezuela_ci"),
            hospital=item.get("hospital"),
            ultimo_lugar=item.get("last_known_location"),
            estado=status,
            notas=item.get("notes"),
            telefono_familiar=item.get("phone"),
        )
        if p:
            results.append(p)
    return results
