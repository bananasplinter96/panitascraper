import re

from .base import persona, s, make_id


def parse(raw: bytes, url: str = "") -> list[dict]:
    html = raw.decode("utf-8", errors="replace")
    results = []
    for card in re.finditer(
        r'<details\s+class="patient-card"[^>]*>(.*?)</details>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        block = card.group(1)
        nombre_m = re.search(r'class="patient-name"[^>]*>([^<]+)<', block)
        cedula_m = re.search(r'class="patient-id"[^>]*>([^<]+)<', block)
        nombre = s(nombre_m.group(1)) if nombre_m else ""
        cedula = s(cedula_m.group(1)) if cedula_m else ""
        if not nombre:
            continue
        fields = {}
        for detail in re.finditer(
            r'<strong>([^<]+)</strong>\s*<span>([^<]*)</span>',
            block, re.DOTALL,
        ):
            key = detail.group(1).strip().lower()
            val = detail.group(2).strip()
            fields[key] = val
        p = persona(
            id=make_id("osiris", nombre, cedula),
            nombre=nombre,
            spider_name="osirisberbesia",
            fuente_url=url,
            tipo_reporte="ingresado",
            cedula=cedula,
            edad=fields.get("edad"),
            hospital=fields.get("hospital"),
            ciudad=fields.get("dirección") or fields.get("direccion"),
            telefono_familiar=fields.get("teléfono") or fields.get("telefono"),
            condicion=fields.get("condición") or fields.get("condicion"),
            cama_sala=fields.get("sala") or fields.get("cama"),
            notas=fields.get("observaciones"),
        )
        if p:
            results.append(p)
    return results
