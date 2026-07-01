"""
Vista previa de duplicados ANTES de correr import_csv_manual.py.

El dedup de import_csv_manual.py solo empareja por cédula o por
nombre+hospital exacto. Las 1,277 personas de La Guaira no tienen
cédula, y el campo hospital que se les asigna (nombre del centro de
acopio) casi nunca coincide con el hospital (vacío) de un registro
previo como "desaparecido" — así que el import real podría crear
personas duplicadas en vez de actualizar su estado.

Este script NO modifica nada. Solo reporta, para cada nombre a
importar, si ya existe alguien con ese mismo nombre en producción
(sin importar el hospital), para decidir si hace falta ampliar el
criterio de dedup antes de correr el import real.

Uso:
    DATABASE_URL=postgresql://<user>:<pass>@localhost:5432/panitasmap \
    python scripts/preview_import_conflicts.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import get_engine
from import_csv_manual import CARIBIA_ROWS, parse_la_guaira_raw, LA_GUAIRA_RAW_PATH

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: define DATABASE_URL (ver .env.example)")


def buscar_por_nombre(session: Session, nombre: str) -> list[tuple]:
    return session.execute(
        text("SELECT id, nombre, tipo_reporte, hospital, cedula FROM personas WHERE nombre ILIKE :n LIMIT 5"),
        {"n": nombre.strip()},
    ).fetchall()


def main():
    engine = get_engine(DATABASE_URL)

    nombres_a_importar: list[str] = []
    for apellido, nombre, *_ in CARIBIA_ROWS:
        nombres_a_importar.append(f"{nombre} {apellido}".strip())
    for nombre, _centro, _fecha in parse_la_guaira_raw(LA_GUAIRA_RAW_PATH):
        nombres_a_importar.append(nombre)

    print(f"Total a importar: {len(nombres_a_importar)}")

    sin_match = 0
    con_match = 0
    detalle_matches = []

    with Session(engine) as session:
        for nombre in nombres_a_importar:
            matches = buscar_por_nombre(session, nombre)
            if matches:
                con_match += 1
                detalle_matches.append((nombre, matches))
            else:
                sin_match += 1

    print(f"\nSin coincidencia por nombre en producción (se insertarían como nuevos): {sin_match}")
    print(f"Con coincidencia por nombre en producción (riesgo de duplicado):        {con_match}")

    if detalle_matches:
        print("\n--- Primeros 30 casos con posible duplicado ---")
        for nombre, matches in detalle_matches[:30]:
            print(f"\n  Importar: '{nombre}'")
            for m in matches:
                print(f"    ya existe: id={m[0]} nombre='{m[1]}' tipo={m[2]} hospital='{m[3]}' cedula={m[4]}")

        if len(detalle_matches) > 30:
            print(f"\n  ... y {len(detalle_matches) - 30} casos más (no mostrados)")


if __name__ == "__main__":
    main()
