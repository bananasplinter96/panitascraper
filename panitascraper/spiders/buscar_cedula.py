"""
╔══════════════════════════════════════════════════════════════════════╗
║        BUSCADOR DE PERSONAS EN VENEZUELA  v4.0                       ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  ORDEN DE CONSULTA (automático, de mayor a menor cobertura):         ║
║                                                                      ║
║  [1] Base local  datos/personas.db  (si fue descargada)              ║
║      → Offline, instantáneo, sin límites                             ║
║                                                                      ║
║  [2] dateas.com  — sin registro                                      ║
║      → Datos: nombre, estado, municipio, parroquia                   ║
║      → Cobertura: hasta aprox. V-25.000.000                          ║
║      → URL: https://www.dateas.com/es/consulta_venezuela             ║
║      → Límite: no documentado (uso moderado recomendado)             ║
║                                                                      ║
║  [3] armandodata.com  — sin registro                                 ║
║      → Datos: nombre, fecha de nacimiento                            ║
║      → Cobertura: hasta aprox. V-30.000.000+                         ║
║      → URL: https://armandodata.com/Personas/Search                  ║
║      → Límite: no documentado (uso moderado recomendado)             ║
║                                                                      ║
║  [4] cedula.com.ve/test.php  — sin registro, abre en navegador       ║
║      → Datos: nombre, RIF, estado, municipio, parroquia,             ║
║               centro electoral                                        ║
║      → Cobertura: hasta aprox. V-30.000.000+ (fuente: CNE)          ║
║      → URL: https://cedula.com.ve/web/test.php                       ║
║      → Límite: 200 consultas/hora (reCAPTCHA manual)                 ║
║      → Se abre automáticamente en tu navegador cuando los            ║
║        primeros dos no encuentran resultado                           ║
║                                                                      ║
║  DESCARGA MASIVA (scrapers):                                         ║
║      scraper_dateas.py      → descarga de dateas.com                 ║
║      scraper_armando.py     → descarga de armandodata.com            ║
║      scraper_cedula_ve.py   → descarga via API cedula.com.ve         ║
║                               (requiere registro gratuito)           ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR     = Path(__file__).parent
DB_PATH      = BASE_DIR / "datos" / "personas.db"
SEP          = "─" * 66
DATEAS_POST  = "https://www.dateas.com/es/consulta_venezuela"
DATEAS_BASE  = "https://www.dateas.com"
ARMANDO_BASE = "https://armandodata.com"
CEDULAVE_URL = "https://cedula.com.ve/web/test.php"

HEADERS_DATEAS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Referer": f"{DATEAS_BASE}/es/public-search/personas_venezuela/venezuela",
    "Origin": DATEAS_BASE,
    "Content-Type": "application/x-www-form-urlencoded",
}
HEADERS_GEN = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
}


# ── Base de datos local ───────────────────────────────────────────────────────
def db_buscar_cedula(cedula: str) -> dict | None:
    if not DB_PATH.exists():
        return None
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute(
            "SELECT nombre, nacimiento, estado, municipio, parroquia, "
            "centro_electoral, rif, fuente FROM personas WHERE cedula=?", (cedula,)
        ).fetchone()
        con.close()
        if row:
            keys = ["nombre","nacimiento","estado","municipio","parroquia",
                    "centro_electoral","rif","fuente"]
            return dict(zip(keys, row))
    except Exception:
        pass
    return None


def db_buscar_nombre(nombre: str) -> list[dict]:
    if not DB_PATH.exists():
        return []
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            "SELECT cedula, nombre, nacimiento, estado, municipio, fuente "
            "FROM personas WHERE nombre LIKE ? LIMIT 50",
            (f"%{nombre.upper()}%",)
        ).fetchall()
        con.close()
        keys = ["cedula","nombre","nacimiento","estado","municipio","fuente"]
        return [dict(zip(keys, r)) for r in rows]
    except Exception:
        return []


# ── dateas.com ────────────────────────────────────────────────────────────────
def dateas_buscar(payload: dict) -> list[dict]:
    body = urllib.parse.urlencode(payload).encode()
    req  = urllib.request.Request(DATEAS_POST, data=body, headers=HEADERS_DATEAS, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode("utf-8", errors="replace")

    rows  = re.findall(r'<tr class="(?:odd|even)">(.*?)</tr>', html, re.DOTALL)
    names = re.findall(r'data-label="Nombre"[^>]*><a[^>]*>([^<]+)<', html)
    locs  = re.findall(r'data-label="Ubicaci.n"[^>]*>([^<]+)<', html)
    slugs = [re.search(r'href="/es/persona_venezuela/([^"]+)"', row) for row in rows]
    slugs = [s.group(1) if s else None for s in slugs]

    return [
        {"nombre": n.strip(), "ubicacion": l.strip(),
         "url": f"{DATEAS_BASE}/es/persona_venezuela/{s}" if s else "",
         "slug": s, "fuente": "dateas.com"}
        for n, l, s in zip(names, locs, slugs)
    ]


def dateas_detalle(slug: str) -> dict:
    req = urllib.request.Request(
        f"{DATEAS_BASE}/es/persona_venezuela/{slug}", headers=HEADERS_GEN
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode("utf-8", errors="replace")

    def f(pat):
        m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    raw   = f(r"[Uu]bicaci.n\s*</[^>]+>\s*<[^>]+>([^<]+)<")
    parts = [p.strip() for p in raw.split(",")]
    return {
        "nacimiento": f(r"Fecha de Nacimiento\s*</[^>]+>\s*<[^>]+>([^<]+)<"),
        "ubicacion":  raw,
        "parroquia":  parts[0] if len(parts) >= 3 else "",
        "municipio":  parts[1] if len(parts) >= 2 else "",
        "estado":     parts[-1] if parts else "",
    }


# ── armandodata.com ───────────────────────────────────────────────────────────
# Estructura real: <h5 class="info-card-title">LABEL</h5>
#                  <p class="info-card-text ...">VALOR</p>
_ARMANDO_PAIR = re.compile(
    r'<h5[^>]*class="info-card-title"[^>]*>(.*?)</h5>\s*'
    r'<p[^>]*class="info-card-text[^"]*"[^>]*>(.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)

def _armando_campos(html: str) -> dict:
    """Extrae todos los pares label→valor de una página de ArmandoData."""
    campos = {}
    for label_raw, value_raw in _ARMANDO_PAIR.findall(html):
        label = re.sub(r'<[^>]+>', '', label_raw).strip()
        value = re.sub(r'<[^>]+>', '', value_raw).strip()
        value = re.sub(r'&[a-zA-Z0-9#]+;', lambda m: {
            '&#xD1;': 'Ñ', '&amp;': '&', '&lt;': '<', '&gt;': '>',
            '&#x00D1;': 'Ñ', '&ntilde;': 'ñ', '&Ntilde;': 'Ñ',
        }.get(m.group(0), m.group(0)), value)
        campos[label] = value
    return campos


def armando_cedula(cedula: str) -> dict | None:
    url = f"{ARMANDO_BASE}/Personas/Detalles?cedula=V{cedula}"
    req = urllib.request.Request(url, headers=HEADERS_GEN)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    campos = _armando_campos(html)
    nombre = campos.get("Nombre Completo", "")
    if not nombre:
        return None
    nac_raw = campos.get("Fecha de Nacimiento (Edad)", campos.get("Fecha de Nacimiento", ""))
    nac = re.sub(r'\s*\(\d+\)\s*$', '', nac_raw).strip()
    return {"nombre": nombre, "nacimiento": nac, "url": url, "fuente": "armandodata.com"}


def armando_nombre(nombre: str) -> list[dict]:
    url = f"{ARMANDO_BASE}/Personas/Search?nombre={urllib.parse.quote(nombre)}"
    req = urllib.request.Request(url, headers=HEADERS_GEN)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    cedulas = list(dict.fromkeys(re.findall(r'/Personas/Detalles\?cedula=V(\d+)', html)))
    results = []
    for ced in cedulas[:10]:
        d = armando_cedula(ced)
        if d:
            d["cedula"] = ced
            results.append(d)
        time.sleep(0.5)
    return results


# ── Presentación ─────────────────────────────────────────────────────────────
def _mostrar_lista(res: list[dict]):
    for i, r in enumerate(res, 1):
        imprimir(r, num=i)
        print()
    if len(res) > 1:
        print(SEP)
        resp = input("  ¿Ver detalle de alguno? Número (o Enter para continuar): ").strip()
        if resp.isdigit():
            idx = int(resp) - 1
            if 0 <= idx < len(res):
                r = res[idx]
                slug = r.get("slug") or (r.get("url","").split("/es/persona_venezuela/")[-1] if r.get("url") else "")
                if slug and "dateas.com" in r.get("url",""):
                    try:
                        r.update(dateas_detalle(slug))
                    except Exception:
                        pass
                print()
                print(SEP)
                imprimir(r)
    print(SEP)


def imprimir(r: dict, num: int | None = None):
    pre = f"  [{num}] " if num else "  "
    print(f"{pre}{r.get('nombre','—')}")
    for label, key in [
        ("Cédula          ", "cedula"),
        ("RIF             ", "rif"),
        ("Nacimiento      ", "nacimiento"),
        ("Estado          ", "estado"),
        ("Municipio       ", "municipio"),
        ("Parroquia       ", "parroquia"),
        ("Centro electoral", "centro_electoral"),
        ("Ubicación       ", "ubicacion"),
    ]:
        v = r.get(key, "")
        if v:
            print(f"       {label}: {v}")

    # Fuente + cómo acceder
    fuente = r.get("fuente", "")
    if fuente:
        print(f"       Fuente          : {fuente}")

    url = r.get("url","")
    if url:
        if "dateas.com" in url:
            print(f"       Perfil dateas   : {url}")
            print(f"         → Abrir en navegador: copia y pega la URL")
        elif "armandodata.com" in url:
            print(f"       Perfil armando  : {url}")
            print(f"         → Abrir en navegador: copia y pega la URL")


# ── Búsqueda por cédula ───────────────────────────────────────────────────────
def buscar_por_cedula(cedula: str):
    # 1) Base local
    local = db_buscar_cedula(cedula)
    if local:
        print("  ✔ Encontrado en base local (datos/personas.db):\n")
        print(SEP)
        imprimir({**local, "cedula": f"V-{cedula}"})
        print(SEP)
        return

    # 2) dateas.com
    print("  [1/3] Consultando dateas.com ...")
    try:
        res = dateas_buscar({"cedula": cedula, "name": ""})
        if res:
            r = res[0]
            if r.get("slug"):
                try:
                    r.update(dateas_detalle(r["slug"]))
                except Exception:
                    pass
            r["cedula"] = f"V-{cedula}"
            print()
            print(SEP)
            print(f"  ✔ Resultado para V-{cedula}:\n")
            imprimir(r)
            print(SEP)
            return
    except Exception as e:
        print(f"     ⚠ Error: {e}")

    # 3) armandodata.com
    print("  [2/3] Consultando armandodata.com ...")
    try:
        arm = armando_cedula(cedula)
        if arm:
            arm["cedula"] = f"V-{cedula}"
            print()
            print(SEP)
            print(f"  ✔ Resultado para V-{cedula}:\n")
            imprimir(arm)
            print(SEP)
            return
    except Exception as e:
        print(f"     ⚠ Error: {e}")

    # 4) Fallback: abrir cedula.com.ve en navegador
    print("  [3/3] No encontrado — abriendo cedula.com.ve en tu navegador...")
    print()
    print(SEP)
    print(f"  ✗ V-{cedula} no encontrada en dateas.com ni armandodata.com")
    print()
    print(f"  Abre: {CEDULAVE_URL}")
    print(f"  → Ingresa la cédula : {cedula}")
    print(f"  → Selecciona        : Venezolana")
    print(f"  → Resuelve el captcha y presiona Consultar")
    print()
    print("  Datos disponibles: nombre, RIF, estado, municipio, parroquia,")
    print("  centro electoral  (fuente: CNE Venezuela · límite: 200/hora)")
    print(SEP)
    try:
        webbrowser.open(CEDULAVE_URL)
    except Exception:
        pass


# ── Búsqueda por nombre ───────────────────────────────────────────────────────
def buscar_por_nombre(nombre: str):
    # 1) Base local
    locales = db_buscar_nombre(nombre)
    if locales:
        print(f"  ✔ {len(locales)} resultado(s) en base local:\n")
        print(SEP)
        for i, r in enumerate(locales, 1):
            imprimir(r, num=i)
            print()
        print(SEP)
        return

    # 2) dateas.com
    print("  [1/2] Consultando dateas.com ...")
    try:
        res = dateas_buscar({"cedula": "", "name": nombre})
        if res:
            print()
            print(SEP)
            print(f"  Se encontraron {len(res)} resultado(s) en dateas.com:\n")
            _mostrar_lista(res)
            return
    except Exception as e:
        print(f"     ⚠ Error: {e}")

    # 3) armandodata.com
    print("  [2/2] Consultando armandodata.com ...")
    try:
        res = armando_nombre(nombre)
        if res:
            print()
            print(SEP)
            print(f"  Se encontraron {len(res)} resultado(s) en armandodata.com:\n")
            _mostrar_lista(res)
            return
    except Exception as e:
        print(f"     ⚠ Error: {e}")

    print()
    print(SEP)
    print("  ✗ No se encontraron resultados.")
    print()
    print(f"  cedula.com.ve/test.php solo permite búsqueda por cédula,")
    print(f"  no por nombre.")
    print(SEP)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Estado de la base local
    db_ok = DB_PATH.exists()
    print(SEP)
    if db_ok:
        try:
            con = sqlite3.connect(DB_PATH)
            count = con.execute("SELECT COUNT(*) FROM personas").fetchone()[0]
            con.close()
            print(f"  ✔ Base local: {count:,} registros en datos/personas.db")
        except Exception:
            print("  ⚠ Base local: archivo encontrado pero no legible")
    else:
        print("  ℹ  Base local: no disponible (ejecuta un scraper para descargar datos)")
    print(SEP)
    print("  ¿Qué deseas buscar?")
    print("  [1] Por número de cédula")
    print("  [2] Por apellidos y nombre")
    print(SEP)

    while True:
        op = input("  Elige (1 o 2): ").strip()
        if op in ("1","2"):
            break
        print("  Opción inválida.")

    print()

    if op == "1":
        raw = input("  Cédula (solo números, sin V/E): ").strip()
        cedula = re.sub(r"[.\-\sVvEe]", "", raw)
        if not cedula.isdigit():
            print("\n  ✗ Solo números.")
            return
        print(f"\n  Buscando V-{cedula}...\n")
        buscar_por_cedula(cedula)
    else:
        nombre = input("  Apellidos y nombre completo: ").strip().upper()
        if len(nombre) < 3:
            print("\n  ✗ Mínimo 3 caracteres.")
            return
        print(f"\n  Buscando '{nombre}'...\n")
        buscar_por_nombre(nombre)


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(__doc__)
    while True:
        main()
        print()
        if input("  ¿Otra búsqueda? (s = sí / Enter = salir): ").strip().lower() not in ("s","si","sí"):
            print("\n  Hasta luego.")
            input("  Presiona Enter para cerrar...")
            break
        print()
