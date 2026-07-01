"""
Reporte de calidad de datos para personas SIN cédula (o con cédula que
no se pudo validar contra el padrón). No borra ni modifica nada — solo
imprime un reporte para revisión manual.

Como la mayoría de los ~187,000 registros sin cédula no se pueden cruzar
contra un padrón externo, este script usa señales indirectas para
detectar basura y posibles duplicados:

  1. Nombres con 3+ consonantes seguidas -> probable error de OCR/transcripción.
  2. Registros "pobres" -> solo tienen nombre, ningún otro dato de contexto.
  3. Variantes del mismo hospital/centro escritas de forma distinta
     (mayúsculas, abreviaturas, con/sin tildes) -> agrupadas para ver
     si conviene unificar nombres de centro.
  4. Posibles duplicados por nombre fonéticamente similar (no exacto),
     agrupados por bloque fonético del primer nombre para no comparar
     los 200k registros entre sí (O(n^2) sería inviable). Dentro de
     cada bloque, si dos nombres distintos son fonéticamente muy
     parecidos Y la edad es compatible (±2 años) o coincide la ciudad/
     hospital normalizado, se reporta como candidato a duplicado.

Uso:
    DATABASE_URL=postgresql://<user>:<pass>@localhost:5432/panitasmap \
    python scripts/data_quality_report.py
"""

import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import get_engine
from fonetica_es import normalizar, codigo_fonetico, comparar

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: define DATABASE_URL (ver .env.example)")

# Campos que aportan contexto además del nombre — si todos están vacíos,
# el registro es "solo un nombre suelto" y muy difícil de verificar.
CAMPOS_CONTEXTO = [
    "edad", "cedula", "sexo", "hospital", "ciudad", "condicion",
    "ultimo_lugar", "descripcion_fisica", "telefono_familiar",
    "contacto_familiar", "notas", "foto_url",
]


def normalizar_hospital(h: str) -> str:
    h = re.sub(r"[^\w\s]", " ", (h or "").upper())
    h = re.sub(r"\s+", " ", h).strip()
    return h


def reporte_consonantes_seguidas(session: Session, limite: int = 40):
    print("\n=== 1. Nombres con 3+ consonantes seguidas (probable error de OCR/transcripción) ===")
    rows = session.execute(text(r"""
        SELECT id, nombre, spider_name FROM personas
        WHERE nombre ~* '[bcdfghjklmnpqrstvwxyzñ]{4,}'
        ORDER BY nombre
        LIMIT :lim
    """), {"lim": limite}).fetchall()
    total = session.execute(text(r"""
        SELECT COUNT(*) FROM personas WHERE nombre ~* '[bcdfghjklmnpqrstvwxyzñ]{4,}'
    """)).scalar()
    print(f"Total encontrados: {total}")
    for r in rows:
        print(f"  id={r[0]}  nombre='{r[1]}'  spider={r[2]}")


def reporte_registros_pobres(session: Session, limite: int = 40):
    print("\n=== 2. Registros sin ningún dato de contexto (solo nombre) ===")
    condiciones = " AND ".join(f"({c} IS NULL OR {c} = '')" for c in CAMPOS_CONTEXTO)
    total = session.execute(text(f"SELECT COUNT(*) FROM personas WHERE {condiciones}")).scalar()
    rows = session.execute(text(f"""
        SELECT id, nombre, spider_name FROM personas
        WHERE {condiciones}
        ORDER BY nombre
        LIMIT :lim
    """), {"lim": limite}).fetchall()
    print(f"Total encontrados: {total}")
    for r in rows:
        print(f"  id={r[0]}  nombre='{r[1]}'  spider={r[2]}")


def reporte_variantes_hospital(session: Session, limite: int = 30):
    print("\n=== 3. Posibles variantes del mismo hospital/centro (mismo texto normalizado) ===")
    rows = session.execute(text("""
        SELECT hospital, COUNT(*) FROM personas
        WHERE hospital IS NOT NULL AND hospital != ''
        GROUP BY hospital
    """)).fetchall()

    grupos: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for hospital, count in rows:
        grupos[normalizar_hospital(hospital)].append((hospital, count))

    variantes = {k: v for k, v in grupos.items() if len(v) > 1}
    print(f"Grupos con más de una variante de escritura: {len(variantes)}")
    for norm, variantes_list in list(variantes.items())[:limite]:
        print(f"\n  Normalizado: '{norm}'")
        for texto, count in sorted(variantes_list, key=lambda x: -x[1]):
            print(f"    '{texto}'  ({count} registros)")


def reporte_duplicados_foneticos(session: Session, limite_bloques: int = 500, limite_reporte: int = 40):
    print("\n=== 4. Posibles duplicados por nombre fonéticamente similar (no exacto) ===")
    rows = session.execute(text("""
        SELECT id, nombre, edad, hospital, ciudad FROM personas
        WHERE nombre IS NOT NULL AND nombre != ''
    """)).fetchall()

    bloques: dict[str, list] = defaultdict(list)
    for row in rows:
        primer_token = normalizar(row[1]).split(" ")[0] if row[1] else ""
        if not primer_token:
            continue
        bloque = codigo_fonetico(primer_token)
        bloques[bloque].append(row)

    candidatos = []
    bloques_grandes = {k: v for k, v in bloques.items() if 1 < len(v) <= 60}  # evita bloques gigantes
    for bloque, personas_bloque in list(bloques_grandes.items())[:limite_bloques]:
        for i in range(len(personas_bloque)):
            for j in range(i + 1, len(personas_bloque)):
                id_a, nom_a, edad_a, hosp_a, ciu_a = personas_bloque[i]
                id_b, nom_b, edad_b, hosp_b, ciu_b = personas_bloque[j]
                if nom_a.strip().lower() == nom_b.strip().lower():
                    continue  # nombre exacto, no es el caso que buscamos aquí
                categoria, score = comparar(nom_a, nom_b)
                if categoria not in ("fonetica",):
                    continue
                edad_compatible = True
                if edad_a and edad_b:
                    try:
                        edad_compatible = abs(int(edad_a) - int(edad_b)) <= 2
                    except ValueError:
                        edad_compatible = True
                # Solo hospital/centro específico cuenta como evidencia de lugar —
                # "ciudad" suele ser un estado entero (ej. "La Guaira") y da falsos
                # positivos entre personas distintas del mismo evento/zona.
                lugar_compatible = normalizar_hospital(hosp_a or "") == normalizar_hospital(hosp_b or "")
                if edad_compatible and (lugar_compatible or (not hosp_a and not hosp_b)):
                    candidatos.append((score, id_a, nom_a, id_b, nom_b, edad_a, edad_b, hosp_a, hosp_b))

    candidatos.sort(key=lambda c: -c[0])
    print(f"Candidatos a duplicado encontrados: {len(candidatos)} (bloqueado por sonido del primer nombre)")
    for score, id_a, nom_a, id_b, nom_b, edad_a, edad_b, hosp_a, hosp_b in candidatos[:limite_reporte]:
        print(f"\n  score={score}")
        print(f"    A: id={id_a} nombre='{nom_a}' edad={edad_a} hospital='{hosp_a}'")
        print(f"    B: id={id_b} nombre='{nom_b}' edad={edad_b} hospital='{hosp_b}'")


def main():
    engine = get_engine(DATABASE_URL)
    with Session(engine) as session:
        reporte_consonantes_seguidas(session)
        reporte_registros_pobres(session)
        reporte_variantes_hospital(session)
        reporte_duplicados_foneticos(session)


if __name__ == "__main__":
    main()
