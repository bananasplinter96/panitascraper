import json

from .base import persona, s


STATE_MAP = {
    "missing": "desaparecido",
    "reunited": "ingresado",
    "found": "ingresado",
    "alive": "ingresado",
    "dead": "fallecido",
}


def parse(raw: bytes, url: str = "") -> list[dict]:
    data = json.loads(raw)
    items = data if isinstance(data, list) else [data]
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "uid" not in item and "name" not in item:
            continue
        state = s(item.get("state"))
        tipo = STATE_MAP.get(state, "desaparecido")
        notas_parts = []
        if item.get("msg"):
            notas_parts.append(item["msg"])
        if item.get("color_pulsera"):
            notas_parts.append(f"Pulsera: {item['color_pulsera']}")
        if item.get("codigo_pulsera"):
            notas_parts.append(f"Código pulsera: {item['codigo_pulsera']}")
        p = persona(
            id=f"tebusco:{item.get('uid', '')}",
            nombre=item.get("name"),
            spider_name="tebusco",
            fuente_url=url,
            tipo_reporte=tipo,
            cedula=item.get("cid"),
            estado=state,
            ultimo_lugar=item.get("place"),
            reportero_nombre=item.get("by_who"),
            telefono_familiar=item.get("phone"),
            notas=" · ".join(notas_parts) if notas_parts else "",
        )
        if p:
            results.append(p)
    return results
