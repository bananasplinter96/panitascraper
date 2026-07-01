import json

from .base import persona, s


def parse(raw: bytes, url: str = "") -> list[dict]:
    data = json.loads(raw)
    items = data.get("data", []) if isinstance(data, dict) else data
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "nombreCompleto" not in item:
            continue
        p = persona(
            id=f"localizados:{item.get('slug', '')}",
            nombre=item.get("nombreCompleto"),
            spider_name="localizadosvenezuela",
            fuente_url=url,
            tipo_reporte="ingresado",
            edad=item.get("edad"),
            cedula=item.get("cedula"),
            condicion=item.get("condicion"),
            hospital=item.get("lugarNombre"),
            ciudad=item.get("direccion"),
            estado="localizado",
            telefono_familiar=item.get("telefono"),
            notas=item.get("observaciones"),
        )
        if p:
            results.append(p)
    return results
