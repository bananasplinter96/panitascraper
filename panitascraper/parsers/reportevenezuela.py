import re

from .base import persona, s, make_id


def parse(raw: bytes, url: str = "") -> list[dict]:
    html = raw.decode("utf-8", errors="replace")
    results = []
    for card in re.finditer(
        r'<section\s+class="tarjeta"[^>]*>(.*?)</section>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        block = card.group(1)
        fields = {}
        for kv in re.finditer(
            r'<span\s+class="ficha__k"[^>]*>([^<]+)</span>\s*'
            r'<span\s+class="ficha__v"[^>]*>([^<]*)</span>',
            block, re.DOTALL,
        ):
            key = kv.group(1).strip().lower()
            val = kv.group(2).strip()
            fields[key] = val
        nombre = s(fields.get("nombre"))
        if not nombre:
            continue
        source_m = re.search(
            r'<span\s+class="sello[^"]*"[^>]*>(?:<span[^>]*></span>)?\s*([^<]+)</span>',
            block, re.DOTALL,
        )
        source = s(source_m.group(1)) if source_m else ""
        titulo_m = re.search(
            r'class="resultado__titulo[^"]*"[^>]*>([^<]+)<',
            block, re.DOTALL,
        )
        titulo = s(titulo_m.group(1)) if titulo_m else ""
        edad_raw = s(fields.get("edad"))
        edad = re.sub(r'\s*a[ñn]os?\s*$', '', edad_raw, flags=re.IGNORECASE)
        p = persona(
            id=make_id("reportevzla", nombre, fields.get("cedula", "")),
            nombre=nombre,
            spider_name="reportevenezuela",
            fuente_url=url,
            tipo_reporte="ingresado",
            edad=edad,
            cedula=fields.get("cedula"),
            hospital=fields.get("lugar"),
            estado=fields.get("estado") or titulo,
            contacto_familiar=fields.get("contacto"),
            notas=source,
        )
        if p:
            results.append(p)
    return results
