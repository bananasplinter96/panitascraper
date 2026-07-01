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
            if any("APELLIDO" in c.upper() for c in row):
                headers = [c.strip().upper() for c in row]
            continue
        if len(row) < len(headers):
            row.extend([""] * (len(headers) - len(row)))
        r = {headers[i]: s(row[i]) for i in range(len(headers))}
        apellido = r.get("APELLIDO(S)", "")
        nombre_raw = r.get("NOMBRE(S)", "")
        nombre = f"{apellido} {nombre_raw}".strip() if apellido or nombre_raw else ""
        if not nombre:
            continue
        cedula = r.get("CÉDULA/ID", "")
        estado_raw = s(r.get("ESTADO/CONDICIÓN", ""))
        if estado_raw.lower() in ("fallecido", "fallecida", "deceased"):
            tipo = "fallecido"
        else:
            tipo = "ingresado"
        cama_parts = []
        if r.get("ÁREA/ZONA"):
            cama_parts.append(r["ÁREA/ZONA"])
        if r.get("PISO/CAMA"):
            cama_parts.append(r["PISO/CAMA"])
        p = persona(
            id=make_id("drive_sismo", nombre, cedula),
            nombre=nombre,
            spider_name="drive_sismo_vzla",
            fuente_url=url,
            tipo_reporte=tipo,
            edad=r.get("EDAD"),
            cedula=cedula,
            sexo={"M": "Masculino", "F": "Femenino"}.get(s(r.get("SEXO", "")), ""),
            hospital=r.get("HOSPITAL/CENTRO"),
            cama_sala=" / ".join(cama_parts) if cama_parts else "",
            ciudad=r.get("PROCEDENCIA"),
            condicion=r.get("DIAGNÓSTICO/SERVICIO"),
            estado=estado_raw,
            contacto_familiar=r.get("FAMILIAR"),
            notas=r.get("COMENTARIOS"),
        )
        if p:
            results.append(p)
    return results
