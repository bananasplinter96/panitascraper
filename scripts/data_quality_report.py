"""
Reporte de calidad de datos centrado en el campo `nombre` y en detección
de duplicados — para personas SIN cédula (o con cédula que no se pudo
validar contra el padrón, ver validate_cedulas.py). No borra ni modifica
nada — solo imprime un reporte para revisión manual.

Para verificaciones de OTROS campos (edad, sexo, cédula, teléfono,
foto_url, consistencia tipo_reporte/estado, encoding, filas duplicadas
exactas) ver scripts/field_integrity_report.py — es el complemento de
este script.

Secciones:
  1. Nombres con 3+ consonantes seguidas -> probable error de OCR/transcripción.
  2. Registros "pobres" -> solo tienen nombre, ningún otro dato de contexto.
  3. Variantes del mismo hospital/centro escritas de forma distinta
     (mayúsculas, abreviaturas, con/sin tildes) -> agrupadas para ver
     si conviene unificar nombres de centro.
  4. Posibles duplicados por nombre fonéticamente similar (no exacto),
     con bloqueo de 2 niveles (primer nombre, y si es muy común también
     prefijo del segundo token) para cubrir el 100% de los registros
     sin que el cálculo sea inviable.
  5. Nombres con dígitos embebidos (ej. número de lista de OCR pegado:
     "12 Yoswaldry Marcano").
  6. Nombres anormalmente largos (>100 caracteres) — indicador temprano
     de concatenación/corrupción, complementario a las secciones 1 y 4
     de fix_name_variants.py.
  7. Nombres genéricos/placeholder ("Desconocido", "Sin Apellido", "N/A", etc.).
  8. Nombre idéntico al valor de hospital o ciudad — dato posiblemente
     metido en la columna equivocada.

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
from fonetica_es import normalizar, codigo_fonetico, comparar, normalizar_hospital

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


_PREFIJO_LEN = 3  # tolera letras faltantes/typos al final del segundo token (ej. "Pere" vs "Perez")


def _clave_bloque(nombre: str, umbral_division: int, conteo_primer_token: dict[str, int]) -> str:
    """
    Bloqueo de dos niveles: por defecto, solo el primer token (nombre).
    Si el primer token es muy común (por encima de umbral_division,
    ej. "maria", "jose"), se agrega el PREFIJO del código fonético del
    segundo token para partir el bloque en pedazos manejables sin
    descartar a nadie. Se usa prefijo (no el código completo) para que
    variantes con letras faltantes al final (ej. "Pere" vs "Perez")
    sigan cayendo en el mismo bloque y se comparen entre sí.
    """
    tokens = normalizar(nombre).split(" ")
    primer = codigo_fonetico(tokens[0]) if tokens and tokens[0] else ""
    if not primer:
        return ""
    if conteo_primer_token.get(primer, 0) <= umbral_division:
        return primer
    segundo_codigo = codigo_fonetico(tokens[1]) if len(tokens) > 1 and tokens[1] else ""
    segundo_prefijo = segundo_codigo[:_PREFIJO_LEN] if segundo_codigo else "(sin_segundo)"
    return f"{primer}:{segundo_prefijo}"


def reporte_duplicados_foneticos(session: Session, limite_reporte: int = 40, umbral_division: int = 60):
    print("\n=== 4. Posibles duplicados por nombre fonéticamente similar (no exacto) ===")
    rows = session.execute(text("""
        SELECT id, nombre, edad, hospital, ciudad FROM personas
        WHERE nombre IS NOT NULL AND nombre != ''
    """)).fetchall()
    print(f"Personas con nombre a analizar: {len(rows)}")

    # Primera pasada: contar cuántas personas comparten cada primer token,
    # para saber a cuáles hay que aplicarles el segundo nivel de bloqueo.
    conteo_primer_token: dict[str, int] = defaultdict(int)
    for row in rows:
        tokens = normalizar(row[1]).split(" ") if row[1] else []
        if tokens and tokens[0]:
            conteo_primer_token[codigo_fonetico(tokens[0])] += 1

    bloques: dict[str, list] = defaultdict(list)
    for row in rows:
        clave = _clave_bloque(row[1], umbral_division, conteo_primer_token)
        if clave:
            bloques[clave].append(row)

    bloques_a_procesar = {k: v for k, v in bloques.items() if len(v) > 1}
    total_comparaciones = sum(len(v) * (len(v) - 1) // 2 for v in bloques_a_procesar.values())
    print(f"Bloques a analizar (tamaño > 1): {len(bloques_a_procesar)} — comparaciones totales estimadas: {total_comparaciones}")

    candidatos = []
    for bloque, personas_bloque in bloques_a_procesar.items():
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
    print(f"Candidatos a duplicado encontrados: {len(candidatos)} (cobertura completa, bloqueo de 2 niveles)")
    for score, id_a, nom_a, id_b, nom_b, edad_a, edad_b, hosp_a, hosp_b in candidatos[:limite_reporte]:
        print(f"\n  score={score}")
        print(f"    A: id={id_a} nombre='{nom_a}' edad={edad_a} hospital='{hosp_a}'")
        print(f"    B: id={id_b} nombre='{nom_b}' edad={edad_b} hospital='{hosp_b}'")


# Con límite de palabra (\y en Postgres) para evitar falsos positivos por
# substring — ej. "na" sin límites haría match con "Ana", "Natera", etc.
NOMBRES_PLACEHOLDER = (
    r"\ydesconocid[oa]\y", r"\ysin\s+apellido\y", r"\yn/?a\y",
    r"\ytest\y", r"\yprueba\y", r"\yxxx\y", r"\ysin\s+nombre\y",
    r"\ysin\s+datos\y", r"\yeliminad[oa]\y",
)


def reporte_nombres_con_digitos(session: Session, limite: int = 40):
    print("\n=== 5. Nombres con dígitos embebidos (ej. número de lista pegado: '12 Yoswaldry Marcano') ===")
    total = session.execute(text(r"SELECT COUNT(*) FROM personas WHERE nombre ~ '[0-9]'")).scalar()
    rows = session.execute(text(r"""
        SELECT id, nombre, spider_name FROM personas
        WHERE nombre ~ '[0-9]'
        ORDER BY nombre
        LIMIT :lim
    """), {"lim": limite}).fetchall()
    print(f"Total encontrados: {total}")
    for r in rows:
        print(f"  id={r[0]}  nombre='{r[1]}'  spider={r[2]}")


def reporte_nombres_largos(session: Session, umbral: int = 100, limite: int = 30):
    print(f"\n=== 6. Nombres anormalmente largos (>{umbral} caracteres — indicador temprano de concatenación/corrupción) ===")
    total = session.execute(
        text("SELECT COUNT(*) FROM personas WHERE LENGTH(nombre) > :u"), {"u": umbral}
    ).scalar()
    rows = session.execute(text("""
        SELECT id, nombre, spider_name FROM personas
        WHERE LENGTH(nombre) > :u
        ORDER BY LENGTH(nombre) DESC
        LIMIT :lim
    """), {"u": umbral, "lim": limite}).fetchall()
    print(f"Total encontrados: {total}")
    for r in rows:
        print(f"  id={r[0]}  len={len(r[1])}  nombre='{r[1][:120]}...'  spider={r[2]}")


def reporte_nombres_placeholder(session: Session, limite: int = 40):
    print("\n=== 7. Nombres genéricos/placeholder ('Desconocido', 'Sin Apellido', 'N/A', 'Test', etc.) ===")
    condiciones = " OR ".join(f"nombre ~* '{p}'" for p in NOMBRES_PLACEHOLDER)
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


def reporte_nombre_igual_a_otro_campo(session: Session, limite: int = 30):
    print("\n=== 8. Nombre idéntico a hospital/ciudad (dato posiblemente en la columna equivocada) ===")
    rows = session.execute(text("""
        SELECT id, nombre, hospital, ciudad, spider_name FROM personas
        WHERE (hospital IS NOT NULL AND hospital != '' AND UPPER(TRIM(nombre)) = UPPER(TRIM(hospital)))
           OR (ciudad IS NOT NULL AND ciudad != '' AND UPPER(TRIM(nombre)) = UPPER(TRIM(ciudad)))
        LIMIT :lim
    """), {"lim": limite}).fetchall()
    total = session.execute(text("""
        SELECT COUNT(*) FROM personas
        WHERE (hospital IS NOT NULL AND hospital != '' AND UPPER(TRIM(nombre)) = UPPER(TRIM(hospital)))
           OR (ciudad IS NOT NULL AND ciudad != '' AND UPPER(TRIM(nombre)) = UPPER(TRIM(ciudad)))
    """)).scalar()
    print(f"Total encontrados: {total}")
    for r in rows:
        print(f"  id={r[0]}  nombre='{r[1]}'  hospital='{r[2]}'  ciudad='{r[3]}'  spider={r[4]}")


def main():
    engine = get_engine(DATABASE_URL)
    with Session(engine) as session:
        reporte_consonantes_seguidas(session)
        reporte_registros_pobres(session)
        reporte_variantes_hospital(session)
        reporte_duplicados_foneticos(session)
        reporte_nombres_con_digitos(session)
        reporte_nombres_largos(session)
        reporte_nombres_placeholder(session)
        reporte_nombre_igual_a_otro_campo(session)


if __name__ == "__main__":
    main()
