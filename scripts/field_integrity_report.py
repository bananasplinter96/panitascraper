"""
Reporte de integridad de campos — complemento de data_quality_report.py
(que se enfoca en `nombre` y duplicados). Este script verifica el resto
de las columnas de `personas`. Solo lectura, no modifica nada.

Secciones:
  1. `edad` no numérica, negativa o absurda (>120).
  2. `sexo` con valores fuera de Masculino/Femenino/vacío.
  3. Cédulas sospechosas: mismo dígito repetido, secuenciales, o
     longitud rara incluso tras normalizar.
  4. Misma cédula asociada a nombres claramente distintos (posible
     error de digitación o de merge) — validación interna, sin
     depender del padrón externo (ver validate_cedulas.py para eso).
  5. Teléfonos con formato inválido (no numérico tras limpiar símbolos,
     o longitud fuera de rango razonable).
  6. `foto_url` reutilizada en más de N personas con nombre distinto
     (posible foto mal asignada / placeholder).
  7. `tipo_reporte` inconsistente con el texto libre de `estado`
     (ej. tipo_reporte='fallecido' pero estado dice "Ingresado").
  8. Encoding roto / mojibake (acentos corruptos, entidades HTML sin
     decodificar).
  9. Filas 100% idénticas en todos los campos relevantes salvo `id`
     (duplicado literal, no necesita fonética).

Uso:
    DATABASE_URL=postgresql://<user>:<pass>@localhost:5432/panitasmap \
    python scripts/field_integrity_report.py
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
from fonetica_es import comparar

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: define DATABASE_URL (ver .env.example)")

SEXO_VALIDOS = {"masculino", "femenino"}
MOJIBAKE_RE = re.compile(r"Ã[©±³¡¨º¤§¦¥¢]|â€|�|&[a-zA-Z]+;|&#\d+;")


def reporte_edad_invalida(session: Session, limite: int = 30):
    print("\n=== 1. Edad no numérica, negativa o > 120 ===")
    rows = session.execute(text("""
        SELECT id, nombre, edad, spider_name FROM personas
        WHERE edad IS NOT NULL AND edad != ''
    """)).fetchall()
    invalidas = []
    for persona_id, nombre, edad, spider in rows:
        try:
            n = int(edad.strip())
            if n < 0 or n > 120:
                invalidas.append((persona_id, nombre, edad, spider))
        except (ValueError, AttributeError):
            invalidas.append((persona_id, nombre, edad, spider))
    print(f"Total encontradas: {len(invalidas)}")
    for persona_id, nombre, edad, spider in invalidas[:limite]:
        print(f"  id={persona_id}  nombre='{nombre}'  edad='{edad}'  spider={spider}")


def reporte_sexo_invalido(session: Session, limite: int = 30):
    print("\n=== 2. Sexo con valores fuera de Masculino/Femenino/vacío ===")
    rows = session.execute(text("""
        SELECT sexo, COUNT(*) FROM personas
        WHERE sexo IS NOT NULL AND sexo != ''
        GROUP BY sexo
    """)).fetchall()
    invalidos = [(s, c) for s, c in rows if s.strip().lower() not in SEXO_VALIDOS]
    print(f"Valores distintos inválidos: {len(invalidos)}")
    for sexo, count in sorted(invalidos, key=lambda x: -x[1])[:limite]:
        print(f"  sexo='{sexo}'  ({count} registros)")


def reporte_cedulas_sospechosas(session: Session, limite: int = 30):
    print("\n=== 3. Cédulas con patrón sospechoso (dígito repetido, secuencial, longitud rara) ===")
    rows = session.execute(text("""
        SELECT id, nombre, cedula, spider_name FROM personas
        WHERE cedula IS NOT NULL AND cedula != ''
    """)).fetchall()

    sospechosas = []
    for persona_id, nombre, cedula, spider in rows:
        norm = re.sub(r"[^0-9]", "", cedula)
        if not norm:
            continue
        es_repetido = len(set(norm)) == 1
        es_secuencial = norm in "0123456789" * 2 or norm[::-1] in "0123456789" * 2
        longitud_rara = not (6 <= len(norm) <= 9)
        if es_repetido or es_secuencial or longitud_rara:
            motivo = []
            if es_repetido:
                motivo.append("dígito repetido")
            if es_secuencial:
                motivo.append("secuencial")
            if longitud_rara:
                motivo.append(f"longitud {len(norm)}")
            sospechosas.append((persona_id, nombre, cedula, ", ".join(motivo), spider))

    print(f"Total encontradas: {len(sospechosas)}")
    for persona_id, nombre, cedula, motivo, spider in sospechosas[:limite]:
        print(f"  id={persona_id}  nombre='{nombre}'  cedula='{cedula}'  motivo={motivo}  spider={spider}")


def reporte_cedula_nombres_distintos(session: Session, limite: int = 30):
    print("\n=== 4. Misma cédula con nombres claramente distintos (posible error de digitación/merge) ===")
    rows = session.execute(text("""
        SELECT regexp_replace(cedula, '[^0-9]', '', 'g') AS cedula_norm,
               array_agg(DISTINCT nombre) AS nombres,
               array_agg(DISTINCT id) AS ids
        FROM personas
        WHERE cedula IS NOT NULL AND cedula != ''
        GROUP BY cedula_norm
        HAVING COUNT(DISTINCT nombre) > 1
    """)).fetchall()

    print(f"Cédulas con más de un nombre asociado: {len(rows)}")
    reportados = 0
    for cedula_norm, nombres, ids in rows:
        if reportados >= limite:
            break
        # Si los nombres son fonéticamente similares entre sí, probablemente
        # es la misma persona (variante de transcripción) — no es el caso
        # que buscamos aquí. Solo reportar si son claramente distintos.
        distintos = True
        if len(nombres) == 2:
            categoria, _ = comparar(nombres[0], nombres[1])
            distintos = categoria == "no_coincide"
        if distintos:
            print(f"  cedula={cedula_norm}  nombres={nombres}  ids={ids}")
            reportados += 1


def reporte_telefonos_invalidos(session: Session, limite: int = 30):
    print("\n=== 5. Teléfonos con formato inválido ===")
    campos = ["telefono_familiar", "reportero_telefono", "contacto_familiar"]
    invalidos_total = 0
    for campo in campos:
        rows = session.execute(text(f"""
            SELECT id, {campo}, spider_name FROM personas
            WHERE {campo} IS NOT NULL AND {campo} != ''
        """)).fetchall()
        invalidos = []
        for persona_id, valor, spider in rows:
            digitos = re.sub(r"[^0-9]", "", valor)
            if not (7 <= len(digitos) <= 15):
                invalidos.append((persona_id, valor, spider))
        invalidos_total += len(invalidos)
        print(f"  Campo '{campo}': {len(invalidos)} inválidos")
        for persona_id, valor, spider in invalidos[:limite // len(campos) or 1]:
            print(f"    id={persona_id}  {campo}='{valor}'  spider={spider}")
    print(f"Total inválidos (todas las columnas de teléfono): {invalidos_total}")


def reporte_foto_reutilizada(session: Session, umbral: int = 3, limite: int = 20):
    print(f"\n=== 6. foto_url reutilizada en {umbral}+ personas con nombre distinto ===")
    rows = session.execute(text("""
        SELECT foto_url, COUNT(DISTINCT nombre) AS n_nombres, COUNT(*) AS n_total
        FROM personas
        WHERE foto_url IS NOT NULL AND foto_url != ''
        GROUP BY foto_url
        HAVING COUNT(DISTINCT nombre) >= :u
        ORDER BY n_nombres DESC
    """), {"u": umbral}).fetchall()
    print(f"Total fotos reutilizadas en {umbral}+ nombres distintos: {len(rows)}")
    for foto_url, n_nombres, n_total in rows[:limite]:
        print(f"  foto_url='{foto_url}'  nombres_distintos={n_nombres}  filas_totales={n_total}")


def reporte_tipo_reporte_vs_estado(session: Session, limite: int = 30):
    print("\n=== 7. tipo_reporte inconsistente con el texto libre de estado ===")
    palabras_por_tipo = {
        "fallecido": ["fallecid", "muert", "deceas", "óbito", "obito", "exitus"],
        "desaparecido": ["desaparecid", "missing", "no localizado", "sin contacto", "sin_contacto"],
        "dado_de_alta": ["alta", "egresad", "localizad", "encontrad", "aparecid", "discharg"],
        "ingresado": ["ingresad", "hospitaliz", "admitid", "internad", "tratamiento"],
    }
    rows = session.execute(text("""
        SELECT id, nombre, tipo_reporte, estado, spider_name FROM personas
        WHERE tipo_reporte IS NOT NULL AND estado IS NOT NULL AND estado != ''
    """)).fetchall()

    inconsistentes = []
    for persona_id, nombre, tipo, estado, spider in rows:
        estado_l = estado.lower()
        tipo_sugerido = None
        for tipo_candidato, palabras in palabras_por_tipo.items():
            if any(p in estado_l for p in palabras):
                tipo_sugerido = tipo_candidato
                break
        if tipo_sugerido and tipo_sugerido != tipo:
            inconsistentes.append((persona_id, nombre, tipo, estado, tipo_sugerido, spider))

    print(f"Total encontradas: {len(inconsistentes)}")
    for persona_id, nombre, tipo, estado, sugerido, spider in inconsistentes[:limite]:
        print(f"  id={persona_id}  nombre='{nombre}'  tipo_reporte='{tipo}'  estado='{estado}'  sugerido='{sugerido}'  spider={spider}")


def reporte_encoding_roto(session: Session, limite: int = 30):
    print("\n=== 8. Encoding roto / mojibake en texto ===")
    campos = ["nombre", "estado", "notas", "hospital", "ciudad"]
    total = 0
    for campo in campos:
        rows = session.execute(text(f"""
            SELECT id, {campo}, spider_name FROM personas
            WHERE {campo} IS NOT NULL AND {campo} != ''
        """)).fetchall()
        encontrados = [(pid, val, sp) for pid, val, sp in rows if MOJIBAKE_RE.search(val or "")]
        total += len(encontrados)
        print(f"  Campo '{campo}': {len(encontrados)} con posible mojibake")
        for pid, val, sp in encontrados[:limite // len(campos) or 1]:
            print(f"    id={pid}  {campo}='{val[:100]}'  spider={sp}")
    print(f"Total con encoding roto (todas las columnas revisadas): {total}")


def reporte_filas_duplicadas_exactas(session: Session, limite: int = 20):
    print("\n=== 9. Filas 100% idénticas salvo id (duplicado literal) ===")
    rows = session.execute(text("""
        SELECT nombre, cedula, edad, sexo, hospital, ciudad, condicion,
               tipo_reporte, array_agg(id) AS ids, COUNT(*) AS n
        FROM personas
        GROUP BY nombre, cedula, edad, sexo, hospital, ciudad, condicion, tipo_reporte
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC
    """)).fetchall()
    print(f"Grupos de filas idénticas: {len(rows)}")
    for nombre, cedula, edad, sexo, hospital, ciudad, condicion, tipo, ids, n in rows[:limite]:
        print(f"  nombre='{nombre}' cedula='{cedula}' edad='{edad}' -> {n} filas idénticas: {ids}")


def main():
    engine = get_engine(DATABASE_URL)
    with Session(engine) as session:
        reporte_edad_invalida(session)
        reporte_sexo_invalido(session)
        reporte_cedulas_sospechosas(session)
        reporte_cedula_nombres_distintos(session)
        reporte_telefonos_invalidos(session)
        reporte_foto_reutilizada(session)
        reporte_tipo_reporte_vs_estado(session)
        reporte_encoding_roto(session)
        reporte_filas_duplicadas_exactas(session)


if __name__ == "__main__":
    main()
