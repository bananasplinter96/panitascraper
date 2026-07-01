"""
Scraper — dateas.com
====================
Descarga registros del padrón electoral venezolano y los guarda en
datos/personas.db (SQLite).

Cobertura estimada: V-1 hasta V-25.000.000 aprox.

USO:
  python scraper_dateas.py                        # rango por defecto 1..25_000_000
  python scraper_dateas.py 1000000 2000000        # rango personalizado
  python scraper_dateas.py --resume               # continúa desde la última cédula guardada

NOTAS:
  • Espera 1.2 s entre requests para no saturar el sitio.
  • Si el proceso se interrumpe, usa --resume para continuar.
  • Los datos se acumulan en datos/personas.db sin borrar lo anterior.
"""

import argparse
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH      = Path(__file__).parent / "datos" / "personas.db"
SEARCH_URL   = "https://www.dateas.com/es/consulta_venezuela"
DETAIL_BASE  = "https://www.dateas.com"
DELAY        = 1.2   # segundos entre requests
BATCH_COMMIT = 100   # filas antes de hacer commit

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Referer": f"{DETAIL_BASE}/es/public-search/personas_venezuela/venezuela",
    "Origin": DETAIL_BASE,
    "Content-Type": "application/x-www-form-urlencoded",
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
            fuente      TEXT DEFAULT 'dateas.com'
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS scraper_progress (
            scraper TEXT PRIMARY KEY,
            last_cedula INTEGER
        )
    """)
    con.commit()


def save_record(con: sqlite3.Connection, cedula: str, record: dict):
    con.execute("""
        INSERT OR REPLACE INTO personas
            (cedula, nombre, nacimiento, ubicacion, estado, municipio, parroquia, fuente)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cedula,
        record.get("nombre", ""),
        record.get("nacimiento", ""),
        record.get("ubicacion", ""),
        record.get("estado", ""),
        record.get("municipio", ""),
        record.get("parroquia", ""),
        "dateas.com",
    ))


def save_progress(con: sqlite3.Connection, cedula_num: int):
    con.execute(
        "INSERT OR REPLACE INTO scraper_progress (scraper, last_cedula) VALUES ('dateas', ?)",
        (cedula_num,)
    )


def last_progress(con: sqlite3.Connection) -> int:
    row = con.execute(
        "SELECT last_cedula FROM scraper_progress WHERE scraper='dateas'"
    ).fetchone()
    return row[0] if row else 0


# ── HTTP ──────────────────────────────────────────────────────────────────────
def buscar_cedula(cedula: str) -> tuple[list[dict], str | None]:
    """POST búsqueda y devuelve (lista_resultados, slug_primero)."""
    body = urllib.parse.urlencode({"cedula": cedula, "name": ""}).encode()
    req  = urllib.request.Request(SEARCH_URL, data=body, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    ✗ Error HTTP búsqueda {cedula}: {e}")
        return [], None

    rows  = re.findall(r'<tr class="(?:odd|even)">(.*?)</tr>', html, re.DOTALL)
    names = re.findall(r'data-label="Nombre"[^>]*><a[^>]*>([^<]+)<', html)
    locs  = re.findall(r'data-label="Ubicaci.n"[^>]*>([^<]+)<', html)
    slugs = [re.search(r'href="/es/persona_venezuela/([^"]+)"', row) for row in rows]
    slugs = [s.group(1) if s else None for s in slugs]

    results = [
        {"nombre": n.strip(), "ubicacion": l.strip(), "slug": s}
        for n, l, s in zip(names, locs, slugs)
    ]
    first_slug = slugs[0] if slugs else None
    return results, first_slug


def detalle_persona(slug: str) -> dict:
    req = urllib.request.Request(f"{DETAIL_BASE}/es/persona_venezuela/{slug}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    ✗ Error HTTP detalle {slug}: {e}")
        return {}

    def f(pat):
        m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    raw_loc = f(r"[Uu]bicaci.n\s*</[^>]+>\s*<[^>]+>([^<]+)<")
    parts   = [p.strip() for p in raw_loc.split(",")]

    return {
        "nacimiento": f(r"Fecha de Nacimiento\s*</[^>]+>\s*<[^>]+>([^<]+)<"),
        "ubicacion":  raw_loc,
        "parroquia":  parts[0] if len(parts) >= 3 else "",
        "municipio":  parts[1] if len(parts) >= 2 else "",
        "estado":     parts[-1] if parts else "",
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Scraper dateas.com → datos/personas.db")
    parser.add_argument("inicio", nargs="?", type=int, default=1)
    parser.add_argument("fin",    nargs="?", type=int, default=25_000_000)
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

    encontrados = 0
    no_encontrados = 0

    try:
        for num in range(inicio, args.fin + 1):
            cedula = str(num)

            resultados, slug = buscar_cedula(cedula)
            time.sleep(DELAY)

            if not resultados or not slug:
                no_encontrados += 1
                if num % 1000 == 0:
                    print(f"  [{num:>10,}] — no encontrado  | OK:{encontrados:,} | NF:{no_encontrados:,}")
            else:
                r = resultados[0]
                det = detalle_persona(slug)
                time.sleep(DELAY)

                record = {**r, **det}
                save_record(con, cedula, record)
                encontrados += 1
                print(f"  [{num:>10,}] ✔ {r['nombre'][:45]:<45} | {det.get('estado','')}")

            # Commit periódico
            if num % BATCH_COMMIT == 0:
                save_progress(con, num)
                con.commit()

    except KeyboardInterrupt:
        print("\n  Interrupción por usuario. Guardando progreso...")

    finally:
        save_progress(con, num if 'num' in dir() else inicio)
        con.commit()
        con.close()
        print(f"\n  Scraping finalizado.")
        print(f"  Encontrados: {encontrados:,} | Sin resultado: {no_encontrados:,}")
        print(f"  Datos guardados en: {DB_PATH}")


if __name__ == "__main__":
    main()
