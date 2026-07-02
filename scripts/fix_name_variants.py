"""
Clasifica y repara registros de `personas` cuyo nombre contiene "/" —
un síntoma que en realidad mezcla 3 patrones distintos, originados
sobre todo en el spider `encuentralos` (que agrega/reconcilia datos de
varias fuentes citizen-report y a veces deja el proceso interno
expuesto en el campo nombre):

  1. variantes_ocr: varias lecturas/grafías del MISMO nombre separadas
     por "/" (ej. "RODRIGO OLIVA JOELVINYER JESUS / RODRIGO OLIVIA ...").
     SE ARREGLA AUTOMÁTICAMENTE: se toma la primera variante como
     nombre canónico y se guardan las demás en notas para no perder
     el dato.

  2. notas_administrativas: no es un nombre en absoluto — es un
     comentario de reconciliación de cédulas de alguna herramienta
     externa (contiene "C.I. registrada como", "ecrespo-github",
     "coincidencia"). NO se repara automáticamente — requiere que
     alguien decida cuál cédula es la correcta.

  3. mensaje_multiple: un mensaje de WhatsApp con varias personas
     mencionadas, pegado como si fuera un solo nombre (empieza con
     "[DD/M, HH:MM"). NO se repara automáticamente — habría que
     separar en varias personas y no hay forma confiable de hacerlo
     sin revisión humana.

Por defecto solo reporta. Usa --apply para aplicar la reparación
automática del grupo 1 únicamente. Los grupos 2 y 3 nunca se tocan
por este script, sin importar --apply.

Uso:
    DATABASE_URL=postgresql://<user>:<pass>@localhost:5432/panitasmap \
    python scripts/fix_name_variants.py [--apply]
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import get_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: define DATABASE_URL (ver .env.example)")

_ADMIN_RE = re.compile(r"C\.I\.\s*registrada|ecrespo-github|coincidencia\s*~?\d+%", re.IGNORECASE)
_WHATSAPP_RE = re.compile(r"^\s*\[\d{1,2}/\d{1,2},\s*\d{1,2}:\d{2}")


def clasificar(nombre: str) -> str:
    if _ADMIN_RE.search(nombre):
        return "notas_administrativas"
    if _WHATSAPP_RE.match(nombre):
        return "mensaje_multiple"
    return "variantes_ocr"


def dividir_variantes(nombre: str) -> tuple[str, list[str]]:
    partes = [p.strip() for p in re.split(r"\s*/\s*", nombre) if p.strip()]
    if not partes:
        return nombre.strip(), []
    return partes[0], partes[1:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplicar la reparación automática del grupo 'variantes_ocr'")
    args = parser.parse_args()

    engine = get_engine(DATABASE_URL)
    with Session(engine) as session:
        rows = session.execute(text(
            "SELECT id, nombre, notas FROM personas WHERE nombre LIKE '%/%'"
        )).fetchall()

        grupos: dict[str, list] = {"variantes_ocr": [], "notas_administrativas": [], "mensaje_multiple": []}
        for persona_id, nombre, notas in rows:
            grupos[clasificar(nombre)].append((persona_id, nombre, notas))

        print(f"Total con '/' en el nombre: {len(rows)}")
        for grupo, items in grupos.items():
            print(f"  {grupo}: {len(items)}")

        print("\n--- Muestra: notas_administrativas (revisión manual, NO se toca) ---")
        for persona_id, nombre, _ in grupos["notas_administrativas"][:10]:
            print(f"  id={persona_id}\n    nombre='{nombre[:150]}...'")

        print("\n--- Muestra: mensaje_multiple (revisión manual, NO se toca) ---")
        for persona_id, nombre, _ in grupos["mensaje_multiple"][:10]:
            print(f"  id={persona_id}\n    nombre='{nombre[:150]}...'")

        print("\n--- Muestra: variantes_ocr (se repara automáticamente con --apply) ---")
        for persona_id, nombre, _ in grupos["variantes_ocr"][:10]:
            canonico, variantes = dividir_variantes(nombre)
            print(f"  id={persona_id}\n    nombre nuevo='{canonico}'\n    variantes guardadas='{' | '.join(variantes)}'")

        if args.apply:
            print("\nAplicando reparación a 'variantes_ocr'...")
            aplicadas = 0
            for persona_id, nombre, notas in grupos["variantes_ocr"]:
                canonico, variantes = dividir_variantes(nombre)
                if not variantes:
                    continue
                nota_variantes = f"[Variantes de nombre detectadas: {' | '.join(variantes)}]"
                nuevas_notas = f"{nota_variantes} {(notas or '')}".strip()
                session.execute(
                    text("UPDATE personas SET nombre = :n, notas = :notas, updated_at = NOW() WHERE id = :id"),
                    {"n": canonico, "notas": nuevas_notas, "id": persona_id},
                )
                aplicadas += 1
            session.commit()
            print(f"Reparadas {aplicadas} filas de 'variantes_ocr'.")
            print(f"'notas_administrativas' ({len(grupos['notas_administrativas'])}) y "
                  f"'mensaje_multiple' ({len(grupos['mensaje_multiple'])}) NO se tocaron — requieren revisión manual.")
        else:
            print("\n(Modo reporte — no se modificó nada. Usa --apply para reparar 'variantes_ocr'.)")


if __name__ == "__main__":
    main()
