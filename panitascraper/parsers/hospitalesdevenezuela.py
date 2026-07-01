import json
import re

from .base import persona, s


def _extract_people_from_rsc(text: str) -> list[dict]:
    """Extract people array from RSC wire format."""
    people_match = re.search(r'"people":\s*(\[.*?\])\s*[,}]', text, re.DOTALL)
    if not people_match:
        return []
    try:
        return json.loads(people_match.group(1))
    except json.JSONDecodeError:
        pass
    records = []
    for obj_match in re.finditer(
        r'\{[^{}]*"firstName"[^{}]*\}', text
    ):
        try:
            records.append(json.loads(obj_match.group()))
        except json.JSONDecodeError:
            continue
    return records


def parse(raw: bytes, url: str = "") -> list[dict]:
    text = raw.decode("utf-8", errors="replace")
    people = _extract_people_from_rsc(text)
    if not people:
        return []
    first_hospital = None
    results = []
    for item in people:
        if not isinstance(item, dict):
            continue
        first_name = s(item.get("firstName"))
        last_name = s(item.get("lastName"))
        nombre = f"{first_name} {last_name}".strip()
        if not nombre:
            continue
        hospital_obj = item.get("hospital")
        if isinstance(hospital_obj, dict):
            first_hospital = hospital_obj
            hospital_name = s(hospital_obj.get("name"))
            hospital_city = s(hospital_obj.get("location"))
        elif first_hospital:
            hospital_name = s(first_hospital.get("name"))
            hospital_city = s(first_hospital.get("location"))
        else:
            hospital_name = s(item.get("currentHospital"))
            hospital_city = s(item.get("foundLocation"))
        notes_raw = s(item.get("notes"))
        STATUS_KEYWORDS = {"FALLECIDO": "fallecido", "ALTA": "ingresado",
                           "HOSPITALIZADO": "ingresado", "UCI": "ingresado",
                           "ESTABLE": "ingresado", "GRAVE": "ingresado"}
        condicion = ""
        estado = "localizado"
        tipo = "ingresado"
        notes_upper = notes_raw.upper()
        for kw, t in STATUS_KEYWORDS.items():
            if kw in notes_upper:
                condicion = notes_raw
                if kw == "FALLECIDO":
                    tipo = "fallecido"
                break
        p = persona(
            id=f"hospitalesvzla:{item.get('id', '')}",
            nombre=nombre,
            spider_name="hospitalesdevenezuela",
            fuente_url=url,
            tipo_reporte=tipo,
            edad=item.get("age"),
            cedula=item.get("idNumber"),
            hospital=hospital_name or s(item.get("currentHospital")),
            ciudad=hospital_city or s(item.get("foundLocation")),
            estado=estado,
            condicion=condicion,
            notas=notes_raw if not condicion else "",
        )
        if p:
            results.append(p)
    return results
