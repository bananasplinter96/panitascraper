import json

from .base import persona, s


def parse(raw: bytes, url: str = "") -> list[dict]:
    data = json.loads(raw)
    items = data.get("items", []) if isinstance(data, dict) else data
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        estado_raw = s(item.get("estado"))
        if estado_raw == "desaparecido":
            tipo = "desaparecido"
        elif estado_raw in ("fallecido", "deceased"):
            tipo = "fallecido"
        else:
            tipo = "ingresado"
        p = persona(
            id=f"encuentralos:{item.get('id', '')}",
            nombre=item.get("nombre"),
            spider_name="encuentralos",
            fuente_url=url,
            tipo_reporte=tipo,
            edad=item.get("edad"),
            cedula=item.get("cedula"),
            sexo=item.get("sexo"),
            foto_url=item.get("foto"),
            estado=estado_raw,
            ultimo_lugar=item.get("ultima_ubicacion"),
            descripcion_fisica=item.get("descripcion"),
            telefono_familiar=item.get("reporta_contacto"),
            hospital=item.get("pv_lugar"),
            condicion=item.get("pv_salud"),
            reportero_nombre=item.get("pv_por"),
            reportero_telefono=item.get("pv_contacto"),
        )
        if p:
            results.append(p)
    return results
