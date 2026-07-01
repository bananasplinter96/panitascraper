import csv
import io

from .base import persona, s, make_id


def parse(raw: bytes, url: str = "") -> list[dict]:
    text = raw.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    results = []
    headers = None
    for row in reader:
        if not row:
            continue
        if headers is None:
            if any("HOSPITAL" in c.upper() for c in row):
                headers = [c.strip().upper() for c in row]
            continue
        if len(row) < len(headers):
            row.extend([""] * (len(headers) - len(row)))
        r = {headers[i]: s(row[i]) for i in range(len(headers))}
        nombre = r.get("APELLIDOS Y NOMBRES", "")
        if not nombre:
            continue
        notas_parts = []
        if r.get("OBSERVACIONES"):
            notas_parts.append(r["OBSERVACIONES"])
        if r.get("TAB DE ORIGEN"):
            notas_parts.append(f"Fuente: {r['TAB DE ORIGEN']}")
        p = persona(
            id=make_id("busquedavzla_sheet", nombre, r.get("CÉDULA / ID")),
            nombre=nombre,
            spider_name="busquedavzla_sheet",
            fuente_url=url,
            tipo_reporte="ingresado",
            edad=r.get("EDAD"),
            cedula=r.get("CÉDULA / ID"),
            sexo={"M": "Masculino", "F": "Femenino"}.get(s(r.get("SEXO", "")), ""),
            hospital=r.get("HOSPITAL"),
            ciudad=r.get("DIRECCIÓN / PROCEDENCIA"),
            telefono_familiar=r.get("TELÉFONO"),
            notas=" · ".join(notas_parts) if notas_parts else "",
        )
        if p:
            results.append(p)
    return results
