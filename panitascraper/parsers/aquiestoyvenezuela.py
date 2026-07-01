import json

from .base import persona, s


def parse(raw: bytes, url: str = "") -> list[dict]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        return []
    if "total" in data and "records" not in data:
        return []
    records = data.get("records", [])
    if not isinstance(records, list):
        return []
    results = []
    for item in records:
        if not isinstance(item, dict):
            continue
        nombre = s(item.get("nombre"))
        if not nombre:
            continue
        estado_raw = s(item.get("estado"))
        if estado_raw.lower() in ("desaparecido", "buscando", "missing"):
            tipo = "desaparecido"
        elif estado_raw.lower() in ("fallecido", "deceased"):
            tipo = "fallecido"
        else:
            tipo = "ingresado"
        p = persona(
            id=f"aquiestoy:{item.get('id', '')}",
            nombre=nombre,
            spider_name="aquiestoyvenezuela",
            fuente_url=url,
            tipo_reporte=tipo,
            edad=item.get("edad"),
            cedula=item.get("cedula"),
            foto_url=item.get("foto_url"),
            estado=estado_raw,
            hospital=item.get("ubicacion_encontrado") or item.get("ciudad"),
            ciudad=item.get("ciudad"),
            ultimo_lugar=item.get("ultima_ubicacion"),
            telefono_familiar=item.get("telefono_contacto"),
            contacto_familiar=item.get("nombre_de_quien_lo_busca"),
            reportero_nombre=item.get("encontrado_por"),
            reportero_telefono=item.get("telefono_quien_encuentra"),
            notas=item.get("observaciones"),
        )
        if p:
            results.append(p)
    return results
