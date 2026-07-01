"""
Cruza personas.cedula/nombre contra el padrón local (datos/personas.db)
y marca cada registro con:

  cedula_validacion:      'exacta' | 'exacta_reordenada' | 'fonetica'
                           | 'no_coincide' | 'sin_registro'
  cedula_nombre_oficial:  nombre tal como aparece en el padrón
  cedula_similitud:       score 0.0-1.0

No borra ni oculta nada — solo marca para que el equipo revise los
'no_coincide' manualmente.

Uso:
    DATABASE_URL=postgresql://<user>:<pass>@localhost:5433/panitasmap \
    python scripts/validate_cedulas.py
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import get_engine
from fonetica_es import comparar

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: define DATABASE_URL (ver .env.example)")
SQLITE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "panitascraper", "spiders", "datos", "personas.db",
)


def cargar_padron() -> dict[str, str]:
    if not os.path.exists(SQLITE_PATH):
        print(f"AVISO: no existe {SQLITE_PATH} — corre primero scrape_target_cedulas.py")
        return {}
    con = sqlite3.connect(SQLITE_PATH)
    rows = con.execute("SELECT cedula, nombre FROM personas WHERE nombre IS NOT NULL AND nombre != ''").fetchall()
    con.close()
    return {cedula: nombre for cedula, nombre in rows}


def main():
    padron = cargar_padron()
    print(f"Padrón cargado: {len(padron)} cédulas")

    engine = get_engine(DATABASE_URL)
    stats = {"exacta": 0, "exacta_reordenada": 0, "fonetica": 0, "no_coincide": 0, "sin_registro": 0}

    with Session(engine) as session:
        rows = session.execute(
            text("SELECT id, cedula, nombre FROM personas WHERE cedula IS NOT NULL AND cedula != ''")
        ).fetchall()
        print(f"Personas con cédula a validar: {len(rows)}")

        for persona_id, cedula, nombre in rows:
            nombre_oficial = padron.get(cedula)

            if not nombre_oficial:
                categoria, score = "sin_registro", None
            else:
                categoria, score = comparar(nombre or "", nombre_oficial)

            stats[categoria] += 1

            session.execute(
                text("""
                    UPDATE personas
                    SET cedula_validacion = :cat,
                        cedula_nombre_oficial = :nom_of,
                        cedula_similitud = :score,
                        updated_at = NOW()
                    WHERE id = :id
                """),
                {
                    "cat": categoria,
                    "nom_of": nombre_oficial,
                    "score": score,
                    "id": persona_id,
                },
            )

        session.commit()

    print("\nResultado:")
    for cat, n in stats.items():
        print(f"  {cat:20s}: {n}")


if __name__ == "__main__":
    main()
