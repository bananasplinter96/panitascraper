import json

from .base import persona, s


def parse(raw: bytes, url: str = "") -> list[dict]:
    data = json.loads(raw)
    items = data if isinstance(data, list) else [data]
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        estado_raw = s(item.get("estado"))
        tipo = "desaparecido" if estado_raw == "buscando" else "ingresado"
        notas_parts = []
        if item.get("apodo"):
            notas_parts.append(f"Apodo: {item['apodo']}")
        if item.get("referencia"):
            notas_parts.append(f"Referencia: {item['referencia']}")
        if item.get("notas"):
            notas_parts.append(item["notas"])
        foto = s(item.get("foto"))
        if foto.startswith("data:"):
            foto = ""
        p = persona(
            id=f"busquedavzla:{item.get('id', '')}",
            nombre=item.get("nombre"),
            spider_name="busquedavzla",
            fuente_url=url,
            tipo_reporte=tipo,
            edad=item.get("edad"),
            estado=estado_raw,
            foto_url=foto,
            ultimo_lugar=item.get("estadoUb"),
            ultimo_contacto=item.get("visto"),
            descripcion_fisica=item.get("desc"),
            reportero_nombre=item.get("repNombre"),
            reportero_telefono=item.get("repTel"),
            notas=" · ".join(notas_parts) if notas_parts else "",
        )
        if p:
            results.append(p)
    return results
