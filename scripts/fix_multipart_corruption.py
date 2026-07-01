"""
Repara filas de `personas` cuyo campo `nombre` quedó corrompido con el
cuerpo crudo de un request multipart/form-data (bug de la API externa
encuentralos.tecnosoft.dev al procesar el formulario de reporte
ciudadano — no es un bug de nuestro spider, que solo lee raw['nombre']
del JSON tal cual).

El blob corrupto normalmente contiene los demás campos del formulario
correctamente etiquetados (name="ultima_ubicacion", name="descripcion",
name="reporta_nombre", name="edad", etc.) — incluyendo, a veces, el
campo name="nombre" real. Este script:

  1. Detecta filas con el patrón de corrupción (boundary multipart).
  2. Extrae todos los pares name="campo" -> valor del blob.
  3. Si hay un campo "nombre" recuperable, lo usa para arreglar la fila
     (y de paso rellena otros campos vacíos con lo que encuentre).
  4. Si NO hay nombre recuperable, la fila queda en una lista de
     "irrecuperables" — se reporta pero NO se borra automáticamente.

Por defecto corre en modo reporte (no modifica nada). Usa --apply para
aplicar las reparaciones recuperables.

Uso:
    DATABASE_URL=postgresql://<user>:<pass>@localhost:5432/panitasmap \
    python scripts/fix_multipart_corruption.py [--apply]
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

CORRUPTO_PATTERN = re.compile(r"Content-Disposition:\s*attachment", re.IGNORECASE)
CAMPO_PATTERN = re.compile(
    r'name="([^"]+)"\s*\r?\n\r?\n(.*?)(?=\r?\n-{10,}|\Z)', re.DOTALL
)

# Mismo mapeo que usa el spider encuentralos.py — el formulario original
# de la API externa usa estos nombres de campo.
CAMPO_A_COLUMNA = {
    "nombre": "nombre",
    "edad": "edad",
    "cedula": "cedula",
    "sexo": "sexo",
    "foto": "foto_url",
    "ultima_ubicacion": "ultimo_lugar",
    "reporta_contacto": "telefono_familiar",
    "descripcion": "descripcion_fisica",
    "pv_por": "reportero_nombre",
    "pv_contacto": "reportero_telefono",
    "pv_lugar": "hospital",
    "pv_salud": "condicion",
}


def extraer_campos(blob: str) -> dict[str, str]:
    campos = {}
    for nombre_campo, valor in CAMPO_PATTERN.findall(blob):
        valor = valor.strip()
        if valor:
            campos[nombre_campo] = valor
    return campos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplicar las reparaciones recuperables (si no, solo reporta)")
    args = parser.parse_args()

    engine = get_engine(DATABASE_URL)
    with Session(engine) as session:
        rows = session.execute(text("""
            SELECT id, nombre, edad, cedula, sexo, foto_url, ultimo_lugar,
                   telefono_familiar, descripcion_fisica, reportero_nombre,
                   reportero_telefono, hospital, condicion
            FROM personas
            WHERE nombre ~* 'Content-Disposition:\\s*attachment'
        """)).fetchall()

        print(f"Filas corruptas encontradas: {len(rows)}")

        recuperables = []
        irrecuperables = []

        for row in rows:
            persona_id = row[0]
            blob = row[1]
            campos_actuales = {
                "edad": row[2], "cedula": row[3], "sexo": row[4], "foto_url": row[5],
                "ultimo_lugar": row[6], "telefono_familiar": row[7],
                "descripcion_fisica": row[8], "reportero_nombre": row[9],
                "reportero_telefono": row[10], "hospital": row[11], "condicion": row[12],
            }
            extraidos = extraer_campos(blob)

            if "nombre" in extraidos:
                update = {"nombre": extraidos["nombre"]}
                for campo_form, columna in CAMPO_A_COLUMNA.items():
                    if columna == "nombre":
                        continue
                    if campo_form in extraidos and not (campos_actuales.get(columna) or "").strip():
                        update[columna] = extraidos[campo_form]
                recuperables.append((persona_id, update))
            else:
                irrecuperables.append((persona_id, extraidos))

        print(f"\nRecuperables (tienen 'nombre' dentro del blob): {len(recuperables)}")
        for persona_id, update in recuperables[:15]:
            print(f"  id={persona_id}  ->  {update}")

        print(f"\nIrrecuperables (sin 'nombre' dentro del blob): {len(irrecuperables)}")
        for persona_id, extraidos in irrecuperables[:15]:
            print(f"  id={persona_id}  campos_encontrados={list(extraidos.keys())}")

        if args.apply:
            print("\nAplicando reparaciones recuperables...")
            for persona_id, update in recuperables:
                set_clauses = ", ".join(f"{col} = :{col}" for col in update) + ", updated_at = NOW()"
                session.execute(
                    text(f"UPDATE personas SET {set_clauses} WHERE id = :id"),
                    {**update, "id": persona_id},
                )
            session.commit()
            print(f"Reparadas {len(recuperables)} filas.")
            print(f"Quedan {len(irrecuperables)} filas irrecuperables SIN modificar — decidir manualmente si se borran.")
        else:
            print("\n(Modo reporte — no se modificó nada. Usa --apply para reparar las recuperables.)")


if __name__ == "__main__":
    main()
