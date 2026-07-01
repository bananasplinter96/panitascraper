import xml.etree.ElementTree as ET

from .base import persona, s

NS = {"pfif": "http://zesty.ca/pfif/1.4/"}

PFIF_STATUS_MAP = {
    "believed_missing": "desaparecido",
    "believed_dead": "fallecido",
    "believed_alive": "ingresado",
    "is_note_author": "ingresado",
    "information_sought": "desaparecido",
}


def parse(raw: bytes, url: str = "") -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    results = []
    for person in root.findall(".//pfif:person", NS):
        pid = person.findtext("pfif:person_record_id", "", NS)
        name = person.findtext("pfif:full_name", "", NS)
        age = person.findtext("pfif:age", "", NS)
        source = person.findtext("pfif:source_name", "", NS)
        photo = person.findtext("pfif:photo_url", "", NS)

        status = ""
        note_text = ""
        note = person.find("pfif:note", NS)
        if note is not None:
            status = note.findtext("pfif:status", "", NS)
            note_text = note.findtext("pfif:text", "", NS)

        tipo = PFIF_STATUS_MAP.get(status, "desaparecido")

        p = persona(
            id=pid or f"busquedaunificada:{name}",
            nombre=name,
            spider_name="busquedaunificadavzla",
            fuente_url=url,
            tipo_reporte=tipo,
            edad=age,
            foto_url=photo,
            estado=status,
            notas=note_text,
            reportero_nombre=source,
        )
        if p:
            results.append(p)
    return results
