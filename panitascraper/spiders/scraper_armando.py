"""
Scraper — armandodata.com
=========================
Descarga registros de personas venezolanas y los guarda en
datos/personas.db (SQLite).

Cobertura estimada: V-1 hasta V-30.000.000+ aprox.

USO:
  python scraper_armando.py                       # rango por defecto 1..30_000_000
  python scraper_armando.py 25000000 30000000     # solo cédulas nuevas
  python scraper_armando.py --resume              # continúa desde la última guardada

NOTAS:
  • Espera 1.0 s entre requests para no saturar el sitio.
  • Si el proceso se interrumpe, usa --resume para continuar.
  • La tabla 'personas' se comparte con scraper_dateas.py.
    Si una cédula ya existe con ubicación (dateas), solo se
    actualiza la fecha de nacimiento (que dateas no tiene).
"""

import argparse
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

DB_PATH     = Path(__file__).parent / "datos" / "personas.db"
ARMANDO_BASE = "https://armandodata.com"
DELAY        = 1.0
BATCH_COMMIT = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Referer": ARMANDO_BASE,
}


# ── Base de datos ─────────────────────────────────────────────────────────────
def init_db(con: sqlite3.Connection):
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


def save_record(con: sqlite3.Connection, cedula: str, nombre: str, nacimiento: str):
    """Inserta o actualiza. Si ya existe entrada de dateas, solo rellena nacimiento."""
    existing = con.execute(
        "SELECT fuente, nacimiento FROM personas WHERE cedula=?", (cedula,)
    ).fetchone()

    if existing:
        # Solo actualizar nacimiento si no lo tenía
        if not existing[1]:
            con.execute(
                "UPDATE personas SET nacimiento=? WHERE cedula=?",
                (nacimiento, cedula)
            )
        # Si la fuente era solo dateas, marcarla como ambas
        if existing[0] == "dateas.com":
            con.execute(
                "UPDATE personas SET fuente='dateas.com + armandodata.com' WHERE cedula=?",
                (cedula,)
            )
    else:
        con.execute("""
            INSERT INTO personas (cedula, nombre, nacimiento, fuente)
            VALUES (?, ?, ?, 'armandodata.com')
        """, (cedula, nombre, nacimiento))


def save_progress(con: sqlite3.Connection, cedula_num: int):
    con.execute(
        "INSERT OR REPLACE INTO scraper_progress (scraper, last_cedula) VALUES ('armando', ?)",
        (cedula_num,)
    )


def last_progress(con: sqlite3.Connection) -> int:
    row = con.execute(
        "SELECT last_cedula FROM scraper_progress WHERE scraper='armando'"
    ).fetchone()
    return row[0] if row else 0


# ── HTTP ──────────────────────────────────────────────────────────────────────
def consultar_cedula(cedula_num: int) -> dict | None:
    """GET /Personas/Detalles?cedula=V{num} y extrae nombre + nacimiento."""
    url = f"{ARMANDO_BASE}/Personas/Detalles?cedula=V{cedula_num}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    ✗ Error HTTP {cedula_num}: {e}")
        return None

    # Estructura: <h5 class="info-card-title">LABEL</h5>
    #             <p class="info-card-text ...">VALOR</p>
    pares = re.findall(
        r'<h5[^>]*class="info-card-title"[^>]*>(.*?)</h5>\s*'
        r'<p[^>]*class="info-card-text[^"]*"[^>]*>(.*?)</p>',
        html, re.IGNORECASE | re.DOTALL,
    )
    campos = {}
    for lbl, val in pares:
        lbl = re.sub(r'<[^>]+>', '', lbl).strip()
        val = re.sub(r'<[^>]+>', '', val).strip()
        val = val.replace('&#xD1;', 'Ñ').replace('&Ntilde;', 'Ñ').replace('&ntilde;', 'ñ')
        campos[lbl] = val

    nombre = campos.get("Nombre Completo", "")
    if not nombre:
        return None

    nac_raw = campos.get("Fecha de Nacimiento (Edad)", campos.get("Fecha de Nacimiento", ""))
    nac = re.sub(r'\s*\(\d+\)\s*$', '', nac_raw).strip()

    return {"nombre": nombre, "nacimiento": nac}


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Scraper armandodata.com → datos/personas.db")
    parser.add_argument("inicio", nargs="?", type=int, default=1)
    parser.add_argument("fin",    nargs="?", type=int, default=30_000_000)
    parser.add_argument("--resume", action="store_true", help="Continuar desde el último guardado")
    args = parser.parse_args()

    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    init_db(con)

    inicio = args.inicio
    if args.resume:
        inicio = last_progress(con) + 1
        print(f"  Reanudando desde cédula {inicio:,}")

    print(f"  Rango: V-{inicio:,} → V-{args.fin:,}")
    print(f"  Base de datos: {DB_PATH}")
    print(f"  Delay: {DELAY}s por cédula")
    print("  Ctrl+C para detener (el progreso se guarda)\n")

    encontrados    = 0
    no_encontrados = 0
    num            = inicio

    try:
        for num in range(inicio, args.fin + 1):
            data = consultar_cedula(num)
            time.sleep(DELAY)

            if not data:
                no_encontrados += 1
                if num % 1000 == 0:
                    print(f"  [{num:>10,}] — no encontrado  | OK:{encontrados:,} | NF:{no_encontrados:,}")
            else:
                save_record(con, str(num), data["nombre"], data["nacimiento"])
                encontrados += 1
                print(f"  [{num:>10,}] ✔ {data['nombre'][:50]:<50} | {data['nacimiento']}")

            if num % BATCH_COMMIT == 0:
                save_progress(con, num)
                con.commit()

    except KeyboardInterrupt:
        print("\n  Interrupción por usuario. Guardando progreso...")

    finally:
        save_progress(con, num)
        con.commit()
        con.close()
        print(f"\n  Scraping finalizado.")
        print(f"  Encontrados: {encontrados:,} | Sin resultado: {no_encontrados:,}")
        print(f"  Datos guardados en: {DB_PATH}")


if __name__ == "__main__":
    main()
