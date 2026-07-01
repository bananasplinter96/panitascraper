import json

from .base import persona, s


def parse(raw: bytes, url: str = "") -> list[dict]:
    data = json.loads(raw)
    items = data if isinstance(data, list) else [data]
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "nombre" not in item:
            continue
        estado_raw = s(item.get("estado"))
        if estado_raw == "aparecido":
            tipo = "ingresado"
        elif estado_raw in ("fallecido", "deceased"):
            tipo = "fallecido"
        else:
            tipo = "desaparecido"
        notas_parts = []
        if item.get("descripcion"):
            notas_parts.append(item["descripcion"])
        if item.get("carrera"):
            notas_parts.append(f"Carrera: {item['carrera']}")
        if item.get("facultad"):
            notas_parts.append(f"Facultad: {item['facultad']}")
        p = persona(
            id=f"ucv:{item.get('id', '')}",
            nombre=item.get("nombre"),
            spider_name="ucv_aparecidos",
            fuente_url=url,
            tipo_reporte=tipo,
            edad=item.get("edad"),
            cedula=item.get("cedula"),
            foto_url=item.get("foto_signed_url"),
            estado=estado_raw,
            ultimo_lugar=item.get("ultima_ubicacion"),
            confirmacion_tipo=item.get("tipo_confirmacion"),
            confirmacion_detalle=item.get("detalles_confirmacion"),
            contacto_familiar=item.get("nombre_contacto"),
            telefono_familiar=item.get("telefono_contacto"),
            reportero_nombre=item.get("registrado_por") or item.get("reportado_aparicion_por"),
            reportero_telefono=item.get("contacto_reportador"),
            notas=" · ".join(notas_parts) if notas_parts else "",
        )
        if p:
            results.append(p)
    return results
