"""
Scraping dirigido: consulta el padrón (dateas.com -> armandodata.com ->
cedula.com.ve) SOLO para las cédulas que ya existen en nuestra tabla
`personas`, en vez de recorrer el rango completo V-1..30M.

Uso:
    DATABASE_URL=postgresql://<user>:<pass>@localhost:5433/panitasmap \
    python scripts/scrape_target_cedulas.py [--limit N] [--resume]

Guarda resultados en panitascraper/spiders/datos/personas.db (mismo
esquema que usan scraper_dateas.py / scraper_armando.py / scraper_cedula_ve.py),
así que se puede seguir alimentando esa base con los scrapers de rango
completo más adelante sin conflicto.
"""

import argparse
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "panitascraper", "spiders"))

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import get_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: define DATABASE_URL (ver .env.example)")
SQLITE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "panitascraper", "spiders", "datos", "personas.db",
)
DELAY = 1.2

# Reutiliza la lógica de scraping de buscar_cedula.py
from buscar_cedula import dateas_buscar, dateas_detalle, armando_cedula  # noqa: E402


def init_sqlite(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS personas (
            cedula      TEXT PRIMARY KEY,
            nombre      TEXT,
            nacimiento  TEXT,
            ubicacion   TEXT,
            estado      TEXT,
            municipio   TEXT,
            parroquia   TEXT,
            fuente      TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS scraper_progress (
            scraper TEXT PRIMARY KEY,
            last_cedula INTEGER
        )
    """)
    con.commit()


def get_target_cedulas(limit: int | None) -> list[str]:
    engine = get_engine(DATABASE_URL)
    with Session(engine) as session:
        q = "SELECT DISTINCT cedula FROM personas WHERE cedula IS NOT NULL AND cedula ~ '^[0-9]{6,9}$' ORDER BY cedula"
        if limit:
            q += f" LIMIT {int(limit)}"
        rows = session.execute(text(q)).fetchall()
    return [r[0] for r in rows]


def consultar_registro(cedula: str) -> dict | None:
    try:
        res = dateas_buscar({"cedula": cedula, "name": ""})
        if res:
            r = res[0]
            if r.get("slug"):
                try:
                    r.update(dateas_detalle(r["slug"]))
                except Exception:
                    pass
            r["fuente"] = "dateas.com"
            return r
    except Exception:
        pass

    try:
        arm = armando_cedula(cedula)
        if arm:
            return arm
    except Exception:
        pass

    return None


def save_result(con: sqlite3.Connection, cedula: str, data: dict) -> None:
    con.execute("""
        INSERT OR REPLACE INTO personas (cedula, nombre, nacimiento, ubicacion, estado, municipio, parroquia, fuente)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cedula, data.get("nombre", ""), data.get("nacimiento", ""),
        data.get("ubicacion", ""), data.get("estado", ""),
        data.get("municipio", ""), data.get("parroquia", ""),
        data.get("fuente", ""),
    ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Limitar cantidad de cédulas a consultar (pruebas)")
    parser.add_argument("--resume", action="store_true", help="Saltar cédulas ya presentes en datos/personas.db")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    con = sqlite3.connect(SQLITE_PATH)
    init_sqlite(con)

    cedulas = get_target_cedulas(args.limit)
    print(f"Cédulas objetivo en personas (Postgres): {len(cedulas)}")

    if args.resume:
        existentes = {r[0] for r in con.execute("SELECT cedula FROM personas").fetchall()}
        antes = len(cedulas)
        cedulas = [c for c in cedulas if c not in existentes]
        print(f"  --resume: {antes - len(cedulas)} ya en datos/personas.db, quedan {len(cedulas)}")

    encontrados = 0
    no_encontrados = 0

    try:
        for i, cedula in enumerate(cedulas, 1):
            data = consultar_registro(cedula)
            if data and data.get("nombre"):
                save_result(con, cedula, data)
                encontrados += 1
            else:
                no_encontrados += 1

            if i % 20 == 0:
                con.commit()
                print(f"  [{i}/{len(cedulas)}] OK:{encontrados} NF:{no_encontrados}")

            time.sleep(DELAY)
    except KeyboardInterrupt:
        print("\nInterrumpido — progreso guardado (usa --resume para continuar).")
    finally:
        con.commit()
        con.close()
        print(f"\nTerminado. Encontrados: {encontrados} | Sin resultado: {no_encontrados}")
        print(f"Guardado en: {SQLITE_PATH}")


if __name__ == "__main__":
    main()
