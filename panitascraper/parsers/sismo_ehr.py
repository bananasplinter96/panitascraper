import json

from .base import persona, s, make_id


STATE_MAP = {
    "deceased": "fallecido",
    "alive": "ingresado",
    "critical": "ingresado",
    "stable": "ingresado",
    "discharged": "ingresado",
}


def parse(raw: bytes, url: str = "") -> list[dict]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        return []
    facility = data.get("facility", {})
    hospital_name = s(facility.get("name"))
    rows = data.get("rows", [])
    results = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        nombre = s(item.get("nombre"))
        if not nombre:
            continue
        estado_raw = s(item.get("estado"))
        tipo = STATE_MAP.get(estado_raw, "ingresado")
        p = persona(
            id=make_id("sismo_ehr", nombre, item.get("cedula")),
            nombre=nombre,
            spider_name="sismo_ehr",
            fuente_url=url,
            tipo_reporte=tipo,
            edad=item.get("edad"),
            cedula=item.get("cedula"),
            sexo={"F": "Femenino", "M": "Masculino"}.get(s(item.get("sexo")), ""),
            estado=estado_raw,
            condicion=estado_raw,
            hospital=hospital_name,
            cama_sala=item.get("servicio"),
        )
        if p:
            results.append(p)
    return results
