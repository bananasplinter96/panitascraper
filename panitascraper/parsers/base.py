import hashlib


def s(val) -> str:
    if val is None:
        return ""
    return str(val).strip()


def make_id(prefix: str, *parts) -> str:
    raw = "|".join(s(p) for p in parts)
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{prefix}:{h}"


def persona(
    id: str,
    nombre: str,
    spider_name: str,
    fuente_url: str = "",
    **kwargs,
) -> dict:
    record = {
        "id": s(id),
        "nombre": s(nombre),
        "spider_name": s(spider_name),
        "fuente_url": s(fuente_url),
        "tipo_reporte": "",
        "edad": "",
        "cedula": "",
        "sexo": "",
        "foto_url": "",
        "hospital": "",
        "ciudad": "",
        "cama_sala": "",
        "condicion": "",
        "contacto_familiar": "",
        "ubicacion_cuerpo": "",
        "confirmacion_tipo": "",
        "confirmacion_detalle": "",
        "ultimo_lugar": "",
        "ultimo_contacto": "",
        "descripcion_fisica": "",
        "telefono_familiar": "",
        "reportero_nombre": "",
        "reportero_telefono": "",
        "estado": "",
        "notas": "",
    }
    for k, v in kwargs.items():
        if k in record and v is not None:
            record[k] = s(v)
    if not record["id"] or not record["nombre"]:
        return None
    return record
