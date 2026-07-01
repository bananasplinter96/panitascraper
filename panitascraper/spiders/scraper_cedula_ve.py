"""
Scraper — cedula.com.ve (API oficial)
======================================
Descarga registros usando la API REST de cedula.com.ve y los guarda
en datos/personas.db (SQLite).

IMPORTANTE — DIFERENCIA ENTRE test.php Y LA API:
  • test.php   → sin registro, pero requiere reCAPTCHA manual.
                 No se puede automatizar. El programa principal
                 la abre en el navegador como último recurso.
  • API REST   → automatizable, requiere registro GRATUITO en
                 https://cedula.com.ve/web/login.php

CONFIGURACIÓN:
  1. Regístrate gratis en https://cedula.com.ve/web/login.php
  2. Copia tu APP_ID y TOKEN desde el panel de usuario
  3. Pégalos en config.ini

LÍMITE API GRATUITA: 200 consultas/hora
  Este scraper usa 18.5 s de delay entre requests para mantenerse
  dentro del límite (≈194 req/hora). Con --fast se omite el delay
  (riesgo de bloqueo temporal si superas las 200/hora).

DATOS DESCARGADOS: nombre, RIF, estado, municipio, parroquia,
                   centro electoral  (fuente: CNE Venezuela)

COBERTURA: V-1 hasta V-30.000.000+ aprox.

USO:
  python scraper_cedula_ve.py                     # rango completo
  python scraper_cedula_ve.py 25000000 30000000   # solo cédulas nuevas
  python scraper_cedula_ve.py --resume            # continuar desde el último guardado
  python scraper_cedula_ve.py --fast              # sin delay (cuidado con el límite)
"""

import argparse
import configparser
import json
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR      = Path(__file__).parent
DB_PATH       = BASE_DIR / "datos" / "personas.db"
CFG_PATH      = BASE_DIR / "config.ini"
API_URL       = "https://api.cedula.com.ve/api/v1"
DELAY_SAFE    = 18.5    # ≈ 194 req/hora, dentro del límite de 200
BATCH_COMMIT  = 50


def cargar_credenciales() -> tuple[str, str]:
    cfg = configparser.ConfigParser()
    cfg.read(CFG_PATH, encoding="utf-8")
    return (
        cfg.get("cedula_ve", "app_id", fallback="").strip(),
        cfg.get("cedula_ve", "token",  fallback="").strip(),
    )


def init_db(con: sqlite3.Connection):
    con.execute("""
        CREATE TABLE IF NOT EXISTS personas (
            cedula           TEXT PRIMARY KEY,
            nombre           TEXT,
            nacimiento       TEXT,
            ubicacion        TEXT,
            estado           TEXT,
            municipio        TEXT,
            parroquia        TEXT,
            centro_electoral TEXT,
            rif              TEXT,
            fuente           TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS scraper_progress (
            scraper TEXT PRIMARY KEY,
            last_cedula INTEGER
        )
    """)
    con.commit()


def save_record(con: sqlite3.Connection, cedula: str, data: dict):
    existing = con.execute(
        "SELECT fuente FROM personas WHERE cedula=?", (cedula,)
    ).fetchone()

    if existing:
        con.execute("""
            UPDATE personas SET
                nombre           = COALESCE(NULLIF(nombre,''),           ?),
                estado           = COALESCE(NULLIF(estado,''),           ?),
                municipio        = COALESCE(NULLIF(municipio,''),        ?),
                parroquia        = COALESCE(NULLIF(parroquia,''),        ?),
                centro_electoral = COALESCE(NULLIF(centro_electoral,''), ?),
                rif              = COALESCE(NULLIF(rif,''),              ?),
                fuente           = 'cedula.com.ve'
            WHERE cedula=?
        """, (data.get("nombre",""), data.get("estado",""), data.get("municipio",""),
              data.get("parroquia",""), data.get("centro_electoral",""),
              data.get("rif",""), cedula))
    else:
        con.execute("""
            INSERT INTO personas (cedula, nombre, estado, municipio, parroquia,
                                  centro_electoral, rif, fuente)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'cedula.com.ve')
        """, (cedula, data.get("nombre",""), data.get("estado",""),
              data.get("municipio",""), data.get("parroquia",""),
              data.get("centro_electoral",""), data.get("rif","")))


def save_progress(con: sqlite3.Connection, num: int):
    con.execute(
        "INSERT OR REPLACE INTO scraper_progress (scraper, last_cedula) VALUES ('cedula_ve', ?)",
        (num,)
    )


def last_progress(con: sqlite3.Connection) -> int:
    row = con.execute(
        "SELECT last_cedula FROM scraper_progress WHERE scraper='cedula_ve'"
    ).fetchone()
    return row[0] if row else 0


def consultar_api(cedula: str, app_id: str, token: str) -> dict | None:
    params = urllib.parse.urlencode({
        "app_id": app_id, "token": token,
        "nacionalidad": "V", "cedula": cedula,
    })
    req = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={"Accept": "application/json", "User-Agent": "BuscarPersonaVE-scraper/4.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RuntimeError("LÍMITE DE HORA ALCANZADO")
        raise

    if body.get("error"):
        return None

    d = body.get("data") or {}
    if not d:
        return None

    nombre = " ".join(filter(None, [
        d.get("primer_nombre"), d.get("segundo_nombre"),
        d.get("primer_apellido"), d.get("segundo_apellido"),
    ]))
    cne = d.get("cne") or {}
    return {
        "nombre":           nombre.strip(),
        "rif":              d.get("rif",""),
        "estado":           cne.get("estado",""),
        "municipio":        cne.get("municipio",""),
        "parroquia":        cne.get("parroquia",""),
        "centro_electoral": cne.get("centro_electoral",""),
    }


def main():
    parser = argparse.ArgumentParser(description="Scraper cedula.com.ve API → datos/personas.db")
    parser.add_argument("inicio", nargs="?", type=int, default=1)
    parser.add_argument("fin",    nargs="?", type=int, default=30_000_000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fast",   action="store_true")
    args = parser.parse_args()

    app_id, token = cargar_credenciales()
    if not app_id or not token:
        print("  ✗ Credenciales no configuradas.")
        print("    1. Regístrate gratis en https://cedula.com.ve/web/login.php")
        print("    2. Copia tu APP_ID y TOKEN")
        print("    3. Edita config.ini con esos valores")
        print()
        print("  NOTA: cedula.com.ve/test.php permite consultas manuales sin registro,")
        print("  pero requiere reCAPTCHA y no puede automatizarse. La API sí.")
        return

    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    init_db(con)

    inicio = args.inicio
    if args.resume:
        inicio = last_progress(con) + 1
        print(f"  Reanudando desde V-{inicio:,}")

    delay = 0 if args.fast else DELAY_SAFE
    print(f"  Rango  : V-{inicio:,} → V-{args.fin:,}")
    print(f"  Delay  : {delay}s {'(sin límite — riesgo de bloqueo)' if not delay else '(≈194 req/hora, dentro del límite gratuito de 200)'}")
    print(f"  Base   : {DB_PATH}")
    print("  Ctrl+C para detener (progreso guardado)\n")

    encontrados = 0
    no_enc      = 0
    num         = inicio

    try:
        for num in range(inicio, args.fin + 1):
            try:
                data = consultar_api(str(num), app_id, token)
            except RuntimeError as e:
                print(f"\n  ⚠ {e} — esperando 65s...")
                time.sleep(65)
                data = consultar_api(str(num), app_id, token)

            if not data:
                no_enc += 1
                if num % 500 == 0:
                    print(f"  [{num:>10,}] NF  | OK:{encontrados:,} NF:{no_enc:,}")
            else:
                save_record(con, str(num), data)
                encontrados += 1
                print(f"  [{num:>10,}] ✔  {data['nombre'][:48]:<48} | {data.get('estado','')}")

            if num % BATCH_COMMIT == 0:
                save_progress(con, num)
                con.commit()

            if delay:
                time.sleep(delay)

    except KeyboardInterrupt:
        print("\n  Detenido.")

    finally:
        save_progress(con, num)
        con.commit()
        con.close()
        print(f"\n  Encontrados   : {encontrados:,}")
        print(f"  Sin resultado : {no_enc:,}")
        print(f"  Base          : {DB_PATH}")


if __name__ == "__main__":
    main()
