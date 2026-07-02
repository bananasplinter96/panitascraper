"""
Verifica cuánta cobertura real tiene la sección 4 de data_quality_report.py
(duplicados fonéticos). Es de solo lectura — no modifica nada, solo mide
el tamaño de los bloques fonéticos para saber cuántas personas quedan
fuera del análisis por los límites de bloques_grandes<=60 y
limite_bloques=500.

Uso:
    DATABASE_URL=postgresql://<user>:<pass>@localhost:5432/panitasmap \
    python scripts/verify_block_coverage.py
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import get_engine
from fonetica_es import normalizar, codigo_fonetico

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: define DATABASE_URL (ver .env.example)")


def main():
    engine = get_engine(DATABASE_URL)
    with Session(engine) as session:
        rows = session.execute(text(
            "SELECT nombre FROM personas WHERE nombre IS NOT NULL AND nombre != ''"
        )).fetchall()

    print(f"Total personas con nombre: {len(rows)}")

    bloques: dict[str, int] = defaultdict(int)
    for (nombre,) in rows:
        primer_token = normalizar(nombre).split(" ")[0] if nombre else ""
        if not primer_token:
            continue
        bloque = codigo_fonetico(primer_token)
        bloques[bloque] += 1

    total_bloques = len(bloques)
    bloques_size1 = {k: v for k, v in bloques.items() if v == 1}
    bloques_2_60 = {k: v for k, v in bloques.items() if 2 <= v <= 60}
    bloques_mas_60 = {k: v for k, v in bloques.items() if v > 60}

    personas_en_2_60 = sum(bloques_2_60.values())
    personas_en_mas_60 = sum(bloques_mas_60.values())

    print(f"\nTotal bloques fonéticos distintos: {total_bloques}")
    print(f"  Bloques de tamaño 1 (sin posible duplicado, no aportan): {len(bloques_size1)}")
    print(f"  Bloques de tamaño 2-60 (SÍ se analizan hoy): {len(bloques_2_60)}  -> personas: {personas_en_2_60}")
    print(f"  Bloques de tamaño >60 (NO se analizan hoy, se descartan): {len(bloques_mas_60)}  -> personas: {personas_en_mas_60}")

    print(f"\n¿Los bloques 2-60 caben dentro del límite de 500 bloques procesados?")
    print(f"  {'SÍ, alcanza' if len(bloques_2_60) <= 500 else f'NO — solo se procesan 500 de {len(bloques_2_60)}, quedan fuera {len(bloques_2_60)-500}'}")

    print("\n--- Los 15 bloques más grandes descartados por 'demasiado grande' (>60) ---")
    for bloque, size in sorted(bloques_mas_60.items(), key=lambda x: -x[1])[:15]:
        print(f"  '{bloque}': {size} personas")


if __name__ == "__main__":
    main()
