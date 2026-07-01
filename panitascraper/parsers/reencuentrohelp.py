import json

from .base import persona, s


STATUS_MAP = {
    "missing": "desaparecido",
    "found": "ingresado",
}


def parse(raw: bytes, url: str = "") -> list[dict]:
    data = json.loads(raw)
    records = data.get("records", []) if isinstance(data, dict) else data
    results = []
    for item in records:
        if not isinstance(item, dict):
            continue
        kind = s(item.get("kind"))
        tipo = STATUS_MAP.get(kind, "ingresado")
        age_min = item.get("age_min")
        age_max = item.get("age_max")
        if age_min is not None and age_max is not None and age_min != age_max:
            edad = f"{age_min}-{age_max}"
        elif age_min is not None:
            edad = str(age_min)
        else:
            edad = ""
        notas_parts = []
        if item.get("senas"):
            notas_parts.append(f"Señas: {item['senas']}")
        if item.get("location_detail"):
            notas_parts.append(f"Detalle ubicación: {item['location_detail']}")
        p = persona(
            id=f"reencuentro:{item.get('id', '')}",
            nombre=item.get("display_name"),
            spider_name="reencuentrohelp",
            fuente_url=url,
            tipo_reporte=tipo,
            edad=edad,
            cedula=item.get("cedula"),
            sexo={"m": "Masculino", "f": "Femenino"}.get(s(item.get("gender")), ""),
            foto_url=item.get("photo_url"),
            estado=s(item.get("status")),
            ultimo_lugar=item.get("region"),
            descripcion_fisica=item.get("description"),
            notas=" · ".join(notas_parts) if notas_parts else "",
        )
        if p:
            results.append(p)
    return results
