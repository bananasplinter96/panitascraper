"""
Importador manual de listas de sobrevivientes/ingresados (PDF -> DB).

Uso:
    DATABASE_URL=postgresql://<user>:<pass>@localhost:5433/panitasmap python scripts/import_csv_manual.py

Inserta/actualiza registros en la tabla `personas` con el mismo criterio de
dedup que usa el pipeline del scraper (id -> cedula -> nombre+hospital).
"""

import hashlib
import os
import re
import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import get_engine

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LA_GUAIRA_RAW_PATH = os.path.join(SCRIPT_DIR, "la_guaira_raw.txt")

_LINE_RE = re.compile(r"^\d+\.\s+(.*?)\s+\(([^,]+),\s*([\d-]+)\)\s*$")


def parse_la_guaira_raw(path: str) -> list[tuple[str, str, str]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = _LINE_RE.match(line)
            if not m:
                continue
            nombre, centro, fecha_raw = m.groups()
            parts = fecha_raw.split("-")
            if len(parts) == 3:
                d, mo, y = parts
                fecha = f"20{y}-{mo}-{d}" if len(y) == 2 else f"{y}-{mo}-{d}"
            else:
                fecha = fecha_raw
            rows.append((nombre.strip(), centro.strip(), fecha))
    return rows

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: define DATABASE_URL (ver .env.example)")
SPIDER_NAME = "import_manual_20260628"

# -------------------------------------------------------------------
# 1) Hospital Ciudad Caribia — pacientes ingresados (28-06-2026)
# -------------------------------------------------------------------
CARIBIA_ROWS = [
    # apellido, nombre, cedula, sexo, edad, procedencia, hora
    ("Nuñez", "Francisco", "9995741", "M", "63", "Tanaguarena", ""),
    ("Velazquez", "Milagro", "14073739", "F", "50", "Playa Grande", ""),
    ("Nuñez", "Wiki", "18534882", "F", "42", "Tanaguarena", ""),
    ("Betencuert", "Ninoska", "13224566", "F", "55", "Los Corales", "8:00 pm"),
    ("Velez", "Haryuri", "12717904", "F", "51", "Caraballeda", "8:00 pm"),
    ("Velez", "Ashley", "31748046", "F", "19", "Caraballeda", "8:00 pm"),
    ("Alvarado", "Lucio", "20191525", "M", "37", "Naiguata", ""),
    ("Nuñez", "Edgar", "20561450", "M", "33", "Naiguata", ""),
    ("Gonzalez", "Pedro", "18816186", "M", "39", "Naiguata (obs)", ""),
    ("Cortez", "Jhonathan", "20792145", "M", "34", "Naiguata", ""),
    ("Borges", "Mariela", "9865570", "F", "57", "Caribe (obs)", ""),
    ("Oropeza", "Yolleida", "9998381", "F", "60", "Caraballeda", "8:30 am"),
    ("Morgado", "Miguelina", "10581580", "F", "63", "Catia La Mar", "11:45 am"),
    ("Masa", "Mariska", "14313108", "F", "48", "Catia La Mar", "11:45 am"),
    ("Gonzalez", "Juan", "5598972", "M", "65", "Playa Grande", "04:20 pm"),
    ("Zambrano", "Edwin", "26376192", "M", "28", "Caribe", "04:21 pm"),
    ("Morales", "Jesus", "11681414", "M", "56", "Tanaguarena", "04:40 pm"),
    ("Francisco", "Leon", "5538724", "M", "32", "Catia La Mar", "07:45 pm"),
]

def upsert_persona(session: Session, persona: dict) -> None:
    if not persona.get("nombre"):
        return
    id_src = f"{SPIDER_NAME}:{persona.get('nombre','')}:{persona.get('cedula','')}:{persona.get('notas','')}"
    persona["id"] = f"{SPIDER_NAME}:{hashlib.md5(id_src.encode()).hexdigest()[:12]}"

    cedula = (persona.get("cedula") or "").strip()
    nombre = (persona.get("nombre") or "").strip()
    hospital = (persona.get("hospital") or "").strip()
    existing_id = None

    if cedula:
        row = session.execute(
            text("SELECT id FROM personas WHERE cedula = :c LIMIT 1"), {"c": cedula}
        ).fetchone()
        if row:
            existing_id = row[0]

    if not existing_id and nombre and hospital:
        row = session.execute(
            text("SELECT id FROM personas WHERE nombre ILIKE :n AND hospital ILIKE :h LIMIT 1"),
            {"n": nombre, "h": hospital},
        ).fetchone()
        if row:
            existing_id = row[0]

    # Fallback: match por nombre solo (sin cédula ni hospital exacto).
    # Estos registros manuales no traen cédula, y el "hospital"/centro que
    # les asignamos rara vez coincide textualmente con lo que ya scrapearon
    # otros spiders (encuentralos, ubicame, etc.) para la misma persona —
    # cada spider guardó su propia fila para la misma persona real.
    #
    # Regla: cualquier fila existente que siga en 'desaparecido' se
    # ACTUALIZA con el nuevo estado (ej. dado_de_alta), guardando el
    # estado anterior en notas para auditoría. Las filas que ya estaban
    # dado_de_alta/ingresado/fallecido no se tocan (ya reflejan la
    # información correcta, no se sobreescriben con datos más pobres).
    if not existing_id and nombre:
        rows = session.execute(
            text("SELECT id, tipo_reporte, notas FROM personas WHERE nombre ILIKE :n"),
            {"n": nombre},
        ).fetchall()
        if rows:
            for row_id, tipo_actual, notas_actual in rows:
                if tipo_actual != "desaparecido":
                    continue  # ya refleja hallazgo/fallecimiento, no tocar
                update_safe = {k: v for k, v in persona.items() if k != "id"}
                update_safe["notas"] = (
                    "[Estado anterior: desaparecido] " + (update_safe.get("notas") or "")
                ).strip() + (f" | {notas_actual}" if notas_actual else "")
                set_clauses = ", ".join(f"{col} = :{col}" for col in update_safe) + ", updated_at = NOW()"
                session.execute(
                    text(f"UPDATE personas SET {set_clauses} WHERE id = :rid"),
                    {**update_safe, "rid": row_id},
                )
            return  # ya se manejó por nombre (actualizado o dejado igual) — no insertar duplicado

    if existing_id:
        update_safe = {k: v for k, v in persona.items() if k != "id"}
        set_clauses = ", ".join(f"{col} = :{col}" for col in update_safe) + ", updated_at = NOW()"
        session.execute(
            text(f"UPDATE personas SET {set_clauses} WHERE id = :id"),
            {**update_safe, "id": existing_id},
        )
    else:
        cols = ", ".join(persona.keys())
        vals = ", ".join(f":{k}" for k in persona)
        session.execute(
            text(f"INSERT INTO personas ({cols}, created_at, updated_at) VALUES ({vals}, NOW(), NOW())"),
            persona,
        )


def main():
    engine = get_engine(DATABASE_URL)
    inserted = 0

    with Session(engine) as session:
        for apellido, nombre, cedula, sexo, edad, procedencia, hora in CARIBIA_ROWS:
            persona = {
                "nombre": f"{nombre} {apellido}".strip(),
                "cedula": cedula,
                "sexo": "Masculino" if sexo == "M" else "Femenino",
                "edad": edad,
                "hospital": "Hospital Ciudad Caribia",
                "ciudad": "La Guaira",
                "tipo_reporte": "ingresado",
                "estado": "Ingresado",
                "notas": f"Procedencia: {procedencia}" + (f" | Hora: {hora}" if hora else ""),
                "spider_name": SPIDER_NAME,
                "fuente_url": "manual:Pacientes Ingresados Hospital Ciudad Caribia (28-6-2026)",
            }
            upsert_persona(session, persona)
            inserted += 1

        la_guaira_rows = parse_la_guaira_raw(LA_GUAIRA_RAW_PATH)
        for nombre, centro, fecha in la_guaira_rows:
            persona = {
                "nombre": nombre,
                "hospital": centro,
                "ciudad": "La Guaira",
                "tipo_reporte": "dado_de_alta",
                "estado": "Localizado con vida",
                "notas": f"Fuente: {centro} ({fecha})",
                "spider_name": SPIDER_NAME,
                "fuente_url": "manual:Lista Unificada de Sobrevivientes La Guaira (28-6-2026)",
            }
            upsert_persona(session, persona)
            inserted += 1

        session.commit()

    print(f"Procesados {inserted} registros.")


if __name__ == "__main__":
    main()
