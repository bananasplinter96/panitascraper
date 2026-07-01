import json

from .base import persona, s


def parse(raw: bytes, url: str = "") -> list[dict]:
    data = json.loads(raw)
    if isinstance(data, dict):
        items = data.get("resultados", data.get("data", []))
    elif isinstance(data, list):
        items = data
    else:
        return []
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "nombreCompleto" not in item:
            continue
        p = persona(
            id=f"localizapacientes:{item.get('id', '')}",
            nombre=item.get("nombreCompleto"),
            spider_name="localizapacientes",
            fuente_url=url,
            tipo_reporte="ingresado",
            edad=item.get("edad"),
            condicion=item.get("condicion"),
            hospital=item.get("hospital"),
            ciudad=item.get("ciudad"),
            estado=item.get("estado"),
            notas=item.get("direccion"),
        )
        if p:
            results.append(p)
    return results
